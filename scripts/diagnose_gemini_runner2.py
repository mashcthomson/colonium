#!/usr/bin/env python3
from __future__ import annotations

import time

from playwright.sync_api import sync_playwright

from colonia.adapters import get_adapter
from colonia.config import load_config
from colonia.models import ServiceName
from colonia.runner import _get_service_page

PROMPT = "Reply with exactly one word: COLONIA_OK"


def main():
    adapter = get_adapter(ServiceName.GEMINI)
    cfg = load_config()
    alpha = next(b for b in cfg.browsers if b.name == "alpha")
    cdp = f"http://127.0.0.1:{alpha.cdp_port}"

    with sync_playwright() as pw:
        chromium = pw.chromium.connect_over_cdp(cdp, timeout=30000)
        ctx = chromium.contexts[0]
        page = _get_service_page(ctx, adapter)
        print("1. initial url:", page.url)

        adapter.new_chat(page)
        print("2. after new_chat:", page.url)
        print("   ensure_ready:", adapter.ensure_ready(page))
        before = adapter.count_responses(page)
        print("3. before_count:", before)

        adapter.send(page, PROMPT)
        print("4. sent, url:", page.url)

        last_text = ""
        stable = 0
        for i in range(240):
            count = adapter.count_responses(page)
            text, _ = adapter.extract_since(page, before)
            streaming = adapter._is_streaming(page)
            ready, last_text, stable = adapter.poll_response_ready(
                page, before, last_text, stable, min_stable_ticks=1
            )
            if i < 20 or i % 10 == 0 or ready or (count != before):
                print(f"  [{i}] c={count} s={streaming} st={stable} r={ready} t={text[:60]!r}")
            if ready:
                print("OK", repr(text))
                return
            time.sleep(0.5)
        print("TIMEOUT final count", adapter.count_responses(page))
        text, _ = adapter.extract_since(page, before)
        print("final text", repr(text))


if __name__ == "__main__":
    main()
