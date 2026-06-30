#!/usr/bin/env python3
"""Diagnose Gemini on fresh chat (new session path)."""

from __future__ import annotations

import time

from playwright.sync_api import sync_playwright

from colonia.adapters import get_adapter
from colonia.models import ServiceName

PROMPT = "Reply with exactly one word: COLONIA_OK (nothing else)."
CDP = "http://127.0.0.1:9222"


def main() -> int:
    adapter = get_adapter(ServiceName.GEMINI)
    with sync_playwright() as pw:
        browser = pw.chromium.connect_over_cdp(CDP, timeout=30000)
        ctx = browser.contexts[0]
        page = ctx.new_page()
        adapter.new_chat(page)
        print("URL after new_chat:", page.url)
        print("ensure_ready:", adapter.ensure_ready(page))
        before = adapter.count_responses(page)
        print("before_count on fresh chat:", before)

        adapter.send(page, PROMPT)
        t0 = time.time()
        last_text = ""
        stable = 0
        for i in range(180):
            count = adapter.count_responses(page)
            text, _ = adapter.extract_since(page, before)
            streaming = adapter._is_streaming(page)
            ready, last_text, stable = adapter.poll_response_ready(
                page, before, last_text, stable, min_stable_ticks=2
            )
            if i % 5 == 0 or ready or count != before:
                print(
                    f"  [{i:03d}] count={count} stream={streaming} stable={stable} "
                    f"ready={ready} text={text[:80]!r}"
                )
            if ready:
                print("DONE in", int((time.time() - t0) * 1000), "ms:", repr(text))
                return 0
            time.sleep(0.5)
        print("TIMEOUT", int((time.time() - t0) * 1000), "ms count=", adapter.count_responses(page))
        text, _ = adapter.extract_since(page, before)
        print("last text:", repr(text))
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
