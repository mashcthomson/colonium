#!/usr/bin/env python3
"""Single-service send probe with debug output."""

import sys
import time

from playwright.sync_api import sync_playwright

from colonium.adapters import get_adapter
from colonium.models import ServiceName

CDP = "http://127.0.0.1:9222"
SERVICE = ServiceName(sys.argv[1] if len(sys.argv) > 1 else "chatgpt")
PROMPT = "Reply with exactly: COLONIUM_OK"


def main():
    adapter = get_adapter(SERVICE)
    with sync_playwright() as pw:
        browser = pw.chromium.connect_over_cdp(CDP, timeout=30000)
        ctx = browser.contexts[0]
        page = ctx.new_page()
        page.goto(adapter.start_url, wait_until="domcontentloaded", timeout=60000)
        page.wait_for_timeout(2000)
        print("URL:", page.url)
        print("ready:", adapter.ensure_ready(page))
        before = adapter.count_responses(page)
        print("assistant count before:", before)
        adapter.send(page, PROMPT)
        print("sent, waiting...")
        time.sleep(3)
        for i in range(60):
            stop = page.evaluate(
                """() => Boolean(document.querySelector('[aria-label*="Stop"], [data-testid*="stop"]'))"""
            )
            n = adapter.count_responses(page)
            print(f"  t={i * 2}s stop={stop} assistants={n}")
            if not stop and n > before and i > 2:
                break
            time.sleep(2)
        text, model = adapter.extract_since(page, before)
        print("model:", model)
        print("text:", repr(text[:500]))
        print("final url:", page.url)


if __name__ == "__main__":
    main()
