#!/usr/bin/env python3
"""Export all Perplexity threads, spaces, and library items via CDP browser session.

Uses Perplexity internal REST API (session cookies from logged-in Chrome).
Inspired by Deplexity (https://github.com/clappingmonkey/Deplexity).

Usage:
  PYTHONPATH=. python perplexity_export.py
  PYTHONPATH=. python perplexity_export.py --cdp-port 9224 --output "./exports/perplexity"
"""

from __future__ import annotations

import argparse
import json
import re
import sys
import time
from concurrent.futures import ThreadPoolExecutor, as_completed
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

API_VERSION = "2.18"
BASE_URL = "https://www.perplexity.ai"
DEFAULT_OUTPUT = Path("./exports/perplexity")
DEFAULT_CDP_PORT = 9224
REQUEST_DELAY_SEC = 1.2
MAX_RETRIES = 8


def safe_print(msg: str) -> None:
    """Print safely on Windows consoles that lack full Unicode support."""
    try:
        print(msg, flush=True)
    except UnicodeEncodeError:
        print(
            msg.encode(sys.stdout.encoding or "utf-8", errors="replace").decode(
                sys.stdout.encoding or "utf-8", errors="replace"
            ),
            flush=True,
        )


def classify_thread_category(tmeta: dict) -> str:
    """Classify a thread from list metadata (display_model / mode)."""
    dm = tmeta.get("display_model") or ""
    mode = tmeta.get("mode") or ""
    if mode == "asi" or dm == "PPLX_ASI":
        return "Computer"
    if dm == "pplx_alpha":
        return "Deep research"
    if dm in ("comet_browser_agent", "comet_browser_agent_sonnet"):
        return "Control browser"
    return "Search"


def slugify(text: str, max_len: int = 80) -> str:
    text = (text or "untitled").strip().lower()
    text = re.sub(r"[^\w\s-]", "", text)
    text = re.sub(r"[\s_-]+", "-", text).strip("-")
    if not text:
        text = "untitled"
    return text[:max_len].rstrip("-")


def extract_answer(blocks: list[dict]) -> str:
    for usage in ("ask_text_0_markdown", "ask_text"):
        for b in blocks:
            if b.get("intended_usage") == usage:
                mb = b.get("markdown_block") or {}
                if mb.get("answer"):
                    return mb["answer"]
    return ""


def extract_sources(blocks: list[dict]) -> list[dict]:
    for b in blocks:
        if b.get("intended_usage") == "web_results":
            wrb = b.get("web_result_block") or {}
            return [
                {
                    "title": s.get("name", ""),
                    "url": s.get("url", ""),
                    "snippet": s.get("snippet", ""),
                }
                for s in wrb.get("web_results") or []
            ]
    return []


def parse_thread_detail(raw: dict, uuid: str, list_meta: dict | None = None) -> dict:
    meta = raw.get("thread_metadata") or {}
    entries = []
    for e in raw.get("entries") or []:
        blocks = e.get("blocks") or []
        entries.append(
            {
                "uuid": e.get("uuid"),
                "query": e.get("query_str", ""),
                "model": e.get("display_model", ""),
                "search_focus": e.get("search_focus", ""),
                "created_at": e.get("entry_created_datetime", ""),
                "answer": extract_answer(blocks),
                "sources": extract_sources(blocks),
            }
        )

    collection = (list_meta or {}).get("collection")
    slug = (list_meta or {}).get("slug") or uuid
    title = meta.get("title") or (list_meta or {}).get("title") or "Untitled"
    return {
        "uuid": uuid,
        "title": title,
        "slug": slug,
        "url": f"{BASE_URL}/search/{slug}",
        "created_at": meta.get("created_at", ""),
        "updated_at": meta.get("updated_at", "")
        or (list_meta or {}).get("last_query_datetime", ""),
        "space": {
            "uuid": collection.get("uuid"),
            "title": collection.get("title"),
            "emoji": collection.get("emoji"),
            "slug": collection.get("slug"),
        }
        if collection
        else None,
        "bookmark_state": (raw.get("entries") or [{}])[0].get("bookmark_state")
        if raw.get("entries")
        else None,
        "entries": entries,
    }


def thread_to_markdown(thread: dict) -> str:
    lines = [
        f"# {thread.get('title', 'Untitled')}",
        "",
        f"- **URL:** {thread.get('url', '')}",
        f"- **UUID:** {thread.get('uuid', '')}",
        f"- **Created:** {thread.get('created_at', '')}",
        f"- **Updated:** {thread.get('updated_at', '')}",
    ]
    if thread.get("space"):
        sp = thread["space"]
        lines.append(f"- **Space:** {sp.get('emoji', '')} {sp.get('title', '')}")
    lines.append("")
    for i, e in enumerate(thread.get("entries") or [], 1):
        lines.extend(
            [
                f"## Q{i}: {e.get('query', '')}",
                "",
                f"*Model: {e.get('model', '')} | Focus: {e.get('search_focus', '')} | {e.get('created_at', '')}*",
                "",
                e.get("answer") or "*(no answer)*",
                "",
            ]
        )
        if e.get("sources"):
            lines.append("### Sources")
            for s in e["sources"]:
                lines.append(f"- [{s.get('title', s.get('url', ''))}]({s.get('url', '')})")
            lines.append("")
    return "\n".join(lines)


class PerplexityExporter:
    def __init__(
        self,
        page,
        output_dir: Path,
        delay: float = REQUEST_DELAY_SEC,
        verbose: bool = False,
        rate_limited: list | None = None,
    ):
        self.page = page
        self.output_dir = output_dir
        self.delay = delay
        self.verbose = verbose
        self._last_req = 0.0
        self.rate_limited = rate_limited if rate_limited is not None else []

    def _rate_limit(self) -> None:
        elapsed = time.time() - self._last_req
        if elapsed < self.delay:
            time.sleep(self.delay - elapsed)
        self._last_req = time.time()

    def _api(self, method: str, path: str, body: dict | None = None) -> Any:
        last_err: Exception | None = None
        for attempt in range(MAX_RETRIES):
            self._rate_limit()
            if self.verbose:
                print(f"  API {method} {path}")
            try:
                return self.page.evaluate(
                    """async ({ method, path, body }) => {
                        const opts = {
                            method,
                            headers: {
                                'Content-Type': 'application/json',
                                'x-app-apiclient': 'default',
                                'x-app-apiversion': '2.18',
                            },
                            credentials: 'include',
                        };
                        if (body) opts.body = JSON.stringify(body);
                        const r = await fetch('https://www.perplexity.ai' + path, opts);
                        if (!r.ok) {
                            const t = await r.text();
                            throw new Error('HTTP ' + r.status + ': ' + t.slice(0, 300));
                        }
                        return r.json();
                    }""",
                    {"method": method, "path": path, "body": body},
                )
            except Exception as e:
                last_err = e
                msg = str(e)
                if "429" in msg or "RATE_LIMITED" in msg:
                    self.rate_limited.append({"path": path, "attempt": attempt + 1})
                    wait = min(60, 5 * (2**attempt))
                    print(
                        f"    Rate limited, waiting {wait}s (attempt {attempt + 1}/{MAX_RETRIES})",
                        flush=True,
                    )
                    time.sleep(wait)
                    self.delay = min(5.0, self.delay * 1.5)
                    continue
                raise
        raise last_err or RuntimeError("API call failed")

    def list_threads(self) -> list[dict]:
        path = f"/rest/thread/list_ask_threads?version={API_VERSION}&source=default"
        all_threads: list[dict] = []
        seen: set[str] = set()
        offset = 0
        limit = 50
        has_next = True

        while has_next:
            body = {
                "limit": limit,
                "ascending": False,
                "offset": offset,
                "search_term": "",
                "exclude_asi": False,
                "include_assets": True,
            }
            raw = self._api("POST", path, body)
            if not raw:
                break
            new_count = 0
            for t in raw:
                uid = t.get("uuid")
                if not uid or uid in seen:
                    continue
                seen.add(uid)
                new_count += 1
                all_threads.append(t)
            has_next = bool(raw[-1].get("has_next_page", False)) if raw else False
            print(
                f"  Thread list: {len(all_threads)} so far (page offset {offset}, has_next={has_next})"
            )
            if new_count == 0:
                break
            offset += len(raw)
        return all_threads

    def list_spaces(self) -> list[dict]:
        path = f"/rest/spaces?version={API_VERSION}&source=default"
        raw = self._api("GET", path)
        spaces = []
        for key in (
            "private_spaces",
            "shared_spaces",
            "invited_spaces",
            "saved_spaces",
            "organization_spaces",
        ):
            for item in raw.get(key) or []:
                spaces.append(
                    {
                        "uuid": item.get("uuid"),
                        "title": item.get("title"),
                        "slug": item.get("slug"),
                        "emoji": item.get("emoji"),
                        "updated": item.get("updated"),
                        "category": key,
                    }
                )
        return spaces

    def list_space_threads(self, space: dict) -> list[dict]:
        """Fetch all threads inside a Space via list_collection_threads."""
        slug = space.get("slug")
        if not slug:
            return []
        all_items: list[dict] = []
        offset = 0
        limit = 50
        while True:
            path = (
                f"/rest/collections/list_collection_threads?collection_slug={slug}"
                f"&limit={limit}&offset={offset}&version={API_VERSION}&source=default"
            )
            raw = self._api("GET", path)
            items = raw if isinstance(raw, list) else (raw.get("threads") or raw.get("items") or [])
            for t in items:
                col = t.get("collection") or {
                    "uuid": space["uuid"],
                    "title": space["title"],
                    "emoji": space.get("emoji"),
                    "slug": space.get("slug"),
                }
                t = dict(t)
                t["collection"] = col
                all_items.append(t)
            if not items or len(items) < limit:
                break
            offset += len(items)
        return all_items

    def get_thread_detail(self, uuid: str) -> dict:
        entries: list[dict] = []
        seen_entry_uuids: set[str] = set()
        offset = 0
        meta: dict = {}
        max_pages = 200  # safety cap (~10k entries)
        for _ in range(max_pages):
            path = (
                f"/rest/thread/{uuid}?with_schematized_response=true&version={API_VERSION}"
                f"&source=default&limit=50&offset={offset}&from_first=true"
                f"&supported_block_use_cases=answer_modes&supported_block_use_cases=preserve_latex"
            )
            page_data = self._api("GET", path)
            if not meta:
                meta = page_data
            page_entries = page_data.get("entries") or []
            if not page_entries:
                break
            new_count = 0
            for e in page_entries:
                eid = e.get("uuid") or ""
                if eid and eid in seen_entry_uuids:
                    continue
                if eid:
                    seen_entry_uuids.add(eid)
                entries.append(e)
                new_count += 1
            if new_count == 0:
                break
            if not page_data.get("has_next_page"):
                break
            offset += len(page_entries)
        combined = dict(meta)
        combined["entries"] = entries
        return combined

    def _save_thread_and_library(self, thread: dict, list_meta: dict | None = None) -> Path:
        out_dir = self.save_thread(thread, list_meta)
        uid = thread["uuid"]
        if thread.get("bookmark_state") == "BOOKMARKED":
            lib_dir = self.output_dir / "library" / f"{slugify(thread['title'])}_{uid[:8]}"
            lib_dir.mkdir(parents=True, exist_ok=True)
            (lib_dir / "thread.json").write_text(
                json.dumps(thread, indent=2, ensure_ascii=False), encoding="utf-8"
            )
            (lib_dir / "thread.md").write_text(thread_to_markdown(thread), encoding="utf-8")
        return out_dir

    def save_thread(self, thread: dict, list_meta: dict | None = None) -> Path:
        folder_name = f"{slugify(thread.get('title', ''))}_{thread['uuid'][:8]}"
        space = thread.get("space")
        if space and space.get("title"):
            base = self.output_dir / "spaces" / slugify(space["title"]) / "threads"
        else:
            base = self.output_dir / "threads"
        out_dir = base / folder_name
        out_dir.mkdir(parents=True, exist_ok=True)
        (out_dir / "thread.json").write_text(
            json.dumps(thread, indent=2, ensure_ascii=False), encoding="utf-8"
        )
        (out_dir / "thread.md").write_text(thread_to_markdown(thread), encoding="utf-8")
        return out_dir

    def run(self, workers: int = 1, cdp_port: int | None = None) -> dict:
        self.output_dir.mkdir(parents=True, exist_ok=True)
        (self.output_dir / "threads").mkdir(exist_ok=True)
        (self.output_dir / "spaces").mkdir(exist_ok=True)
        (self.output_dir / "library").mkdir(exist_ok=True)

        def log(msg: str) -> None:
            safe_print(msg)

        log("Phase 1: Listing threads from library...")
        thread_list = self.list_threads()
        library_count = len(thread_list)
        log(f"  Found {library_count} threads in library/history")

        log("Phase 2: Listing spaces...")
        spaces = self.list_spaces()
        log(f"  Found {len(spaces)} spaces")
        spaces_index = self.output_dir / "spaces" / "index.json"
        spaces_index.write_text(json.dumps(spaces, indent=2, ensure_ascii=False), encoding="utf-8")

        log("Phase 2b: Listing threads per space...")
        seen_uuids = {t["uuid"] for t in thread_list if t.get("uuid")}
        space_thread_counts: dict[str, int] = {}
        space_only_added = 0
        for sp in spaces:
            sp_threads = self.list_space_threads(sp)
            space_thread_counts[sp["uuid"]] = len(sp_threads)
            added = 0
            for t in sp_threads:
                uid = t.get("uuid")
                if uid and uid not in seen_uuids:
                    seen_uuids.add(uid)
                    thread_list.append(t)
                    added += 1
                    space_only_added += 1
            log(f"  Space '{sp['title']}': {len(sp_threads)} threads ({added} new)")
        if space_only_added:
            log(f"  Added {space_only_added} space-only threads not in library list")
        log(f"  Total unique threads to export: {len(thread_list)}")

        log("Phase 3: Fetching thread details...")
        exported: list[dict] = []
        errors: list[dict] = []
        # Build UUID index from existing exports for fast resume
        exported_uuids: set[str] = set()
        exported_by_uuid: dict[str, dict] = {}
        for p in self.output_dir.rglob("thread.json"):
            try:
                d = json.loads(p.read_text(encoding="utf-8"))
                if d.get("uuid"):
                    exported_uuids.add(d["uuid"])
                    if d["uuid"] not in exported_by_uuid or "/threads/" in str(p).replace(
                        "\\", "/"
                    ):
                        exported_by_uuid[d["uuid"]] = d
            except Exception:
                pass

        skipped = 0
        pending: list[tuple[int, dict]] = []
        for i, tmeta in enumerate(thread_list, 1):
            uid = tmeta["uuid"]
            title = (tmeta.get("title") or "Untitled")[:60]
            if uid in exported_uuids:
                skipped += 1
                if uid in exported_by_uuid:
                    exported.append(exported_by_uuid[uid])
                if self.verbose:
                    log(f"  [{i}/{len(thread_list)}] SKIP (exists) {title}")
                continue
            pending.append((i, tmeta))

        def fetch_one(item: tuple[int, dict]) -> tuple[dict | None, dict | None, list[dict]]:
            i, tmeta = item
            uid = tmeta["uuid"]
            title = (tmeta.get("title") or "Untitled")[:60]
            safe_print(f"  [{i}/{len(thread_list)}] {title}")
            try:
                if workers > 1 and cdp_port is not None:
                    return _export_single_thread(
                        cdp_port, self.output_dir, self.delay, self.verbose, tmeta
                    )
                raw = self.get_thread_detail(uid)
                thread = parse_thread_detail(raw, uid, tmeta)
                self._save_thread_and_library(thread, tmeta)
                return thread, None, []
            except Exception as e:
                safe_print(f"    ERROR: {e}")
                return None, {"uuid": uid, "title": tmeta.get("title"), "error": str(e)}, []

        if pending:
            if workers > 1 and cdp_port is not None:
                log(f"  Fetching {len(pending)} threads with {workers} workers...")
                with ThreadPoolExecutor(max_workers=workers) as pool:
                    futures = {pool.submit(fetch_one, item): item for item in pending}
                    for fut in as_completed(futures):
                        try:
                            thread, err, rl = fut.result()
                        except Exception as e:
                            i, tmeta = futures[fut]
                            safe_print(f"    WORKER ERROR [{i}]: {e}")
                            errors.append(
                                {
                                    "uuid": tmeta.get("uuid"),
                                    "title": tmeta.get("title"),
                                    "error": str(e),
                                }
                            )
                            continue
                        self.rate_limited.extend(rl)
                        if thread:
                            exported.append(thread)
                        if err:
                            errors.append(err)
            else:
                for item in pending:
                    thread, err, rl = fetch_one(item)
                    self.rate_limited.extend(rl)
                    if thread:
                        exported.append(thread)
                    if err:
                        errors.append(err)

        # Per-space summary folders
        for sp in spaces:
            sp_dir = self.output_dir / "spaces" / slugify(sp["title"])
            sp_dir.mkdir(parents=True, exist_ok=True)
            sp_threads = [t for t in exported if (t.get("space") or {}).get("uuid") == sp["uuid"]]
            (sp_dir / "space.json").write_text(
                json.dumps(
                    {
                        **sp,
                        "thread_count": len(sp_threads),
                        "thread_uuids": [t["uuid"] for t in sp_threads],
                    },
                    indent=2,
                    ensure_ascii=False,
                ),
                encoding="utf-8",
            )

        list_by_uuid = {t["uuid"]: t for t in thread_list if t.get("uuid")}
        category_counts_list = {
            cat: 0 for cat in ("Search", "Control browser", "Deep research", "Computer")
        }
        for t in thread_list:
            category_counts_list[classify_thread_category(t)] += 1

        category_counts_disk = {
            cat: 0 for cat in ("Search", "Control browser", "Deep research", "Computer")
        }
        disk_uuids: set[str] = set()
        for t in exported:
            uid = t.get("uuid")
            if not uid or uid in disk_uuids:
                continue
            disk_uuids.add(uid)
            meta = list_by_uuid.get(uid, {})
            entries = t.get("entries") or []
            dm = (entries[0].get("model") if entries else "") or meta.get("display_model") or ""
            mode = meta.get("mode") or ""
            category_counts_disk[classify_thread_category({"display_model": dm, "mode": mode})] += 1

        manifest = {
            "exported_at": datetime.now(timezone.utc).isoformat(),
            "api_version": API_VERSION,
            "cdp_method": "playwright_cdp",
            "counts": {
                "threads_listed_library": library_count,
                "threads_from_spaces_only": space_only_added,
                "threads_total_unique": len(thread_list),
                "threads_exported": len(exported),
                "threads_unique_on_disk": len(disk_uuids),
                "threads_skipped_existing": skipped,
                "threads_failed": len(errors),
                "rate_limited_events": len(self.rate_limited),
                "spaces": len(spaces),
                "library_bookmarked": len(
                    [t for t in exported if t.get("bookmark_state") == "BOOKMARKED"]
                ),
                "threads_in_spaces": len([t for t in exported if t.get("space")]),
            },
            "category_counts_list": category_counts_list,
            "category_counts_disk": category_counts_disk,
            "category_targets": {
                "Search": 522,
                "Control browser": 27,
                "Deep research": 13,
                "Computer": 2,
            },
            "space_thread_counts_from_list": space_thread_counts,
            "rate_limited": self.rate_limited,
            "errors": errors,
        }
        (self.output_dir / "manifest.json").write_text(
            json.dumps(manifest, indent=2, ensure_ascii=False), encoding="utf-8"
        )
        (self.output_dir / "thread_index.json").write_text(
            json.dumps(
                [
                    {"uuid": t["uuid"], "title": t.get("title"), "space": t.get("space")}
                    for t in exported
                ],
                indent=2,
                ensure_ascii=False,
            ),
            encoding="utf-8",
        )
        return manifest


def _export_single_thread(
    port: int,
    output_dir: Path,
    delay: float,
    verbose: bool,
    tmeta: dict,
) -> tuple[dict | None, dict | None, list[dict]]:
    """Worker: own CDP connection per thread (sync Playwright is not thread-safe)."""
    from playwright.sync_api import sync_playwright

    uid = tmeta["uuid"]
    rate_limited: list[dict] = []
    try:
        with sync_playwright() as pw:
            browser = pw.chromium.connect_over_cdp(f"http://127.0.0.1:{port}", timeout=30000)
            ctx = browser.contexts[0] if browser.contexts else browser.new_context()
            page = next((p for p in ctx.pages if "perplexity.ai" in (p.url or "")), None)
            if page is None:
                page = ctx.new_page()
            exporter = PerplexityExporter(
                page, output_dir, delay=delay, verbose=verbose, rate_limited=rate_limited
            )
            raw = exporter.get_thread_detail(uid)
            thread = parse_thread_detail(raw, uid, tmeta)
            exporter._save_thread_and_library(thread, tmeta)
        return thread, None, rate_limited
    except Exception as e:
        return None, {"uuid": uid, "title": tmeta.get("title"), "error": str(e)}, rate_limited


def find_perplexity_port(ports: list[int]) -> int | None:
    import http.client

    for port in ports:
        if port < 1 or port > 65535:
            continue
        conn = http.client.HTTPConnection("127.0.0.1", port, timeout=2)
        try:
            conn.request("GET", "/json/list")
            response = conn.getresponse()
            tabs = json.loads(response.read())
            if any("perplexity.ai" in t.get("url", "") for t in tabs):
                return port
        except Exception:
            pass
        finally:
            conn.close()
    return None


def main() -> int:
    parser = argparse.ArgumentParser(
        description="Export all Perplexity chats via CDP browser session"
    )
    parser.add_argument(
        "--cdp-port", type=int, default=None, help="Chrome CDP port (auto-detect if omitted)"
    )
    parser.add_argument("--output", type=Path, default=DEFAULT_OUTPUT, help="Output directory")
    parser.add_argument(
        "--delay",
        type=float,
        default=REQUEST_DELAY_SEC,
        help="Delay between API requests (seconds)",
    )
    parser.add_argument("--verbose", "-v", action="store_true")
    parser.add_argument(
        "--workers", type=int, default=1, help="Parallel thread detail fetchers (default 1)"
    )
    args = parser.parse_args()

    port = args.cdp_port
    if port is None:
        port = find_perplexity_port([9224, 9222, 9223, 9225, 9226, 9233])
        if port is None:
            print(
                "ERROR: No Chrome CDP port with Perplexity tabs found. Log in at perplexity.ai first.",
                file=sys.stderr,
            )
            return 1
        print(f"Auto-detected Perplexity on CDP port {port}")

    from playwright.sync_api import sync_playwright

    cdp_url = f"http://127.0.0.1:{port}"
    print(f"Connecting to Chrome via CDP: {cdp_url}")

    with sync_playwright() as pw:
        browser = pw.chromium.connect_over_cdp(cdp_url, timeout=30000)
        ctx = browser.contexts[0] if browser.contexts else browser.new_context()
        page = None
        for p in ctx.pages:
            if "perplexity.ai" in (p.url or ""):
                page = p
                break
        if page is None:
            page = ctx.new_page()
            page.goto(f"{BASE_URL}/library", wait_until="domcontentloaded", timeout=60000)
            page.wait_for_timeout(3000)
        else:
            if "perplexity.ai" not in page.url:
                page.goto(f"{BASE_URL}/library", wait_until="domcontentloaded", timeout=60000)
                page.wait_for_timeout(2000)

        print(f"Using tab: {page.url[:80]}")

        exporter = PerplexityExporter(page, args.output, delay=args.delay, verbose=args.verbose)
        manifest = exporter.run(workers=max(1, args.workers), cdp_port=port)

    print("\n=== EXPORT COMPLETE ===")
    print(json.dumps(manifest["counts"], indent=2))
    print("Category counts (listed):", json.dumps(manifest.get("category_counts_list", {})))
    print("Category counts (disk):", json.dumps(manifest.get("category_counts_disk", {})))
    print("Category targets:", json.dumps(manifest.get("category_targets", {})))
    if manifest.get("rate_limited"):
        print(f"Rate-limited events: {len(manifest['rate_limited'])}")
    print(f"Output: {args.output}")
    if manifest["errors"]:
        print(f"WARNING: {len(manifest['errors'])} threads failed — see manifest.json")
        return 2
    return 0


if __name__ == "__main__":
    sys.exit(main())
