from __future__ import annotations

import time
from pathlib import Path
from urllib.parse import urlparse

from playwright.sync_api import sync_playwright

from colonium.adapters import get_adapter
from colonium.adapters.base import BAD_URL_MARKERS
from colonium.config import load_config
from colonium.models import BrowserInstance, CouncilResponse, ServiceName, TaskStatus
from colonium.prompt_profiles import apply_prompt_profile
from colonium.sessions import SessionStore
from colonium.text import normalize_response_markdown


def run_single_task(
    *,
    browser: BrowserInstance,
    service: ServiceName,
    prompt: str,
    files: list[Path],
    fresh_chat: bool,
    session_id: str | None,
    timeout_ms: int,
    session_store: SessionStore | None = None,
    artifact_root: Path | None = None,
) -> CouncilResponse:
    adapter = get_adapter(service)
    cdp_url = f"http://127.0.0.1:{browser.cdp_port}"
    started = time.time()
    store = session_store or SessionStore()

    effective_browser = browser.name
    if session_id:
        effective_browser = store.resolve_browser(session_id, browser.name)
        browser = _browser_by_name(effective_browser) or browser

    with sync_playwright() as pw:
        chromium = pw.chromium.connect_over_cdp(cdp_url, timeout=30000)
        ctx = chromium.contexts[0] if chromium.contexts else chromium.new_context()
        page = _open_task_page(ctx, adapter, session_id=session_id, fresh_chat=fresh_chat)
        initial_navigation = _ensure_service_page_loaded(page, adapter)

        status = adapter.ensure_ready(page)
        if status == TaskStatus.AUTH_REQUIRED:
            return CouncilResponse(
                browser=browser.name,
                service=service.value,
                status=TaskStatus.AUTH_REQUIRED,
                url=page.url,
                latency_ms=int((time.time() - started) * 1000),
                error="Login required — open this browser on Colonium Desktop 2 and sign in",
            )

        if session_id and not fresh_chat:
            binding = store.get_binding(session_id, browser.name, service)
            if binding:
                adapter.open_thread(page, binding.thread_url)
            else:
                adapter.new_chat(page)
        else:
            if session_id and fresh_chat:
                store.delete_binding(session_id, browser.name, service)
            if not initial_navigation:
                adapter.new_chat(page)

        status = adapter.ensure_ready(page)
        if status == TaskStatus.AUTH_REQUIRED:
            return CouncilResponse(
                browser=browser.name,
                service=service.value,
                status=TaskStatus.AUTH_REQUIRED,
                url=page.url,
                latency_ms=int((time.time() - started) * 1000),
                error="Login required after navigation",
            )

        before_send_count = adapter.count_responses(page)
        prepared_prompt = apply_prompt_profile(
            prompt,
            browser=browser.name,
            service=service.value,
        )
        prepare_prompt = getattr(adapter, "prepare_prompt", None)
        if prepare_prompt:
            prepare_prompt(page, prepared_prompt)
        adapter.send(page, prepared_prompt, files or None)
        adapter.wait_until_done(page, timeout_ms, baseline_count=before_send_count)
        text, model_label = adapter.extract_since(page, before_send_count)
        text = normalize_response_markdown(text, service=service.value)
        after_count = adapter.count_responses(page)
        latency = int((time.time() - started) * 1000)

        if not text.strip():
            return CouncilResponse(
                browser=browser.name,
                service=service.value,
                model_label=model_label,
                status=TaskStatus.ERROR,
                text="",
                url=page.url,
                latency_ms=latency,
                error="Empty response — check input selectors or login state",
            )

        if session_id:
            store.save_binding(
                session_id,
                browser.name,
                service,
                page.url or adapter.start_url,
                after_count,
            )

        response = CouncilResponse(
            browser=browser.name,
            service=service.value,
            model_label=model_label,
            status=TaskStatus.DONE,
            text=text,
            url=page.url,
            latency_ms=latency,
            attachments_sent=[str(f) for f in files] if files else [],
        )
        if artifact_root:
            response.artifacts_received = _collect_response_artifacts(
                page,
                artifact_root=artifact_root,
                browser=browser.name,
                service=service.value,
                text=text,
            )
        return response


def _browser_by_name(name: str) -> BrowserInstance | None:
    cfg = load_config()
    for b in cfg.browsers:
        if b.name == name:
            return b
    return None


def _collect_response_artifacts(
    page,
    *,
    artifact_root: Path,
    browser: str,
    service: str,
    text: str = "",
):
    from colonium.artifacts import collect_code_artifacts, collect_page_artifacts

    records = collect_page_artifacts(
        page=page,
        artifact_root=artifact_root,
        browser=browser,
        service=service,
    )
    records.extend(
        collect_code_artifacts(
            text,
            artifact_root=artifact_root,
            browser=browser,
            service=service,
        )
    )
    return records


def _is_usable_tab(url: str, host: str) -> bool:
    u = (url or "").lower()
    if host not in u:
        return False
    return not any(marker in u for marker in BAD_URL_MARKERS)


def _normalized_host(url: str) -> str:
    host = urlparse(url or "").hostname or ""
    return host.lower().removeprefix("www.")


def _is_service_tab(url: str, host: str) -> bool:
    return _normalized_host(url) == _normalized_host(f"https://{host}")


def _ensure_service_page_loaded(page, adapter) -> bool:
    host = adapter.start_url.split("/")[2]
    if _is_service_tab(page.url or "", host):
        return False
    adapter.new_chat(page)
    return True


def _is_start_page(url: str, start_url: str) -> bool:
    parsed = urlparse(url or "")
    start = urlparse(start_url or "")
    if _normalized_host(url) != _normalized_host(start_url):
        return False
    path = parsed.path.rstrip("/") or "/"
    start_path = start.path.rstrip("/") or "/"
    return path == start_path


def _prefer_thread_pages(pages, adapter):
    return sorted(
        pages,
        key=lambda page: _is_start_page(page.url or "", adapter.start_url),
    )


def _close_duplicate_service_tabs(ctx, adapter, keep_page) -> None:
    host = adapter.start_url.split("/")[2]
    for page in list(ctx.pages):
        if page is keep_page:
            continue
        if _is_service_tab(page.url or "", host):
            try:
                page.close()
            except Exception:
                pass


def _get_service_page(ctx, adapter):
    host = adapter.start_url.split("/")[2]
    service_pages = [p for p in ctx.pages if _is_service_tab(p.url or "", host)]

    for p in _prefer_thread_pages(service_pages, adapter):
        if _is_usable_tab(p.url or "", host):
            _close_duplicate_service_tabs(ctx, adapter, p)
            return p

    if service_pages:
        page = _prefer_thread_pages(service_pages, adapter)[0]
        _close_duplicate_service_tabs(ctx, adapter, page)
        return page

    for p in ctx.pages:
        if _is_usable_tab(p.url or "", host):
            _close_duplicate_service_tabs(ctx, adapter, p)
            return p
    page = ctx.new_page()
    return page


def _open_task_page(ctx, adapter, *, session_id: str | None, fresh_chat: bool):
    if session_id and not fresh_chat:
        return _get_service_page(ctx, adapter)
    return ctx.new_page()
