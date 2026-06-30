#!/usr/bin/env python3
"""Diagnose Gemini adapter on alpha via CDP."""

from __future__ import annotations

import json
import time

from playwright.sync_api import sync_playwright

from colonium.adapters import get_adapter
from colonium.models import ServiceName
from colonium.placeholders import is_thinking_placeholder

PROMPT = "Reply with exactly one word: COLONIUM_OK (nothing else)."
CDP = "http://127.0.0.1:9222"


def main() -> int:
    adapter = get_adapter(ServiceName.GEMINI)

    with sync_playwright() as pw:
        browser = pw.chromium.connect_over_cdp(CDP, timeout=30000)
        ctx = browser.contexts[0]
        page = None
        for p in ctx.pages:
            if "gemini.google.com" in (p.url or ""):
                page = p
                break
        if page is None:
            page = ctx.new_page()
            page.goto(adapter.start_url, wait_until="domcontentloaded", timeout=60000)
            page.wait_for_timeout(3000)

        print("URL:", page.url)
        print("ensure_ready:", adapter.ensure_ready(page))
        print("has_input:", adapter.has_input(page))

        before = adapter.count_responses(page)
        print("before_count:", before)

        probe = page.evaluate(
            """() => {
                const sel = "message-content, .model-response-text, div.markdown, [data-message-id]";
                const nodes = [];
                for (const s of sel.split(',').map(x => x.trim())) {
                    document.querySelectorAll(s).forEach(n => nodes.push({
                        sel: s,
                        tag: n.tagName,
                        cls: (n.className || '').toString().slice(0, 80),
                        text: (n.innerText || '').slice(0, 120),
                    }));
                }
                const inputs = [];
                for (const s of "rich-textarea div[contenteditable='true'], div.ql-editor, rich-textarea".split(',')) {
                    document.querySelectorAll(s.trim()).forEach(n => inputs.push({
                        sel: s.trim(),
                        visible: !!(n.offsetParent),
                        text: (n.innerText || '').slice(0, 40),
                    }));
                }
                const stop = [];
                for (const s of '[aria-label*="Stop"], [data-testid*="stop"]'.split(',')) {
                    document.querySelectorAll(s.trim()).forEach(n => stop.push(s.trim()));
                }
                return {nodes: nodes.slice(-6), inputs, stop, title: document.title};
            }"""
        )
        print("DOM probe:", json.dumps(probe, indent=2))

        print("\nSending prompt...")
        adapter.send(page, PROMPT)
        t0 = time.time()
        last_text = ""
        stable = 0
        for i in range(120):
            count = adapter.count_responses(page)
            text, model = adapter.extract_since(page, before)
            streaming = adapter._is_streaming(page)
            ready, last_text, stable = adapter.poll_response_ready(
                page, before, last_text, stable, min_stable_ticks=2
            )
            ph = is_thinking_placeholder(text)
            print(
                f"  [{i:02d}] count={count} stream={streaming} stable={stable} "
                f"placeholder={ph} ready={ready} text={text[:80]!r}"
            )
            if ready and not ph:
                break
            time.sleep(0.5)
        else:
            print("TIMEOUT after", int((time.time() - t0) * 1000), "ms")
            return 1

        print("\nDONE in", int((time.time() - t0) * 1000), "ms")
        print("final:", repr(text))
        return 0


if __name__ == "__main__":
    raise SystemExit(main())
