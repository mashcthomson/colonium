#!/usr/bin/env python3
from __future__ import annotations

import time

from playwright.sync_api import sync_playwright

from colonium.adapters import get_adapter
from colonium.config import load_config
from colonium.models import ServiceName
from colonium.runner import _get_service_page

PROMPT = "Reply with exactly one word: COLONIUM_OK"


def try_send(label, page, adapter, before):
    page.bring_to_front()
    adapter.send(page, PROMPT)
    for i in range(30):
        count = adapter.count_responses(page)
        text, _ = adapter.extract_since(page, before)
        if count > before or text.strip():
            print(f"  {label}: SUCCESS at {i * 0.5}s count={count} text={text[:40]!r}")
            return True
        time.sleep(0.5)
    print(f"  {label}: FAILED count={adapter.count_responses(page)}")
    return False


def main():
    adapter = get_adapter(ServiceName.GEMINI)
    cfg = load_config()
    alpha = next(b for b in cfg.browsers if b.name == "alpha")
    with sync_playwright() as pw:
        ctx = pw.chromium.connect_over_cdp(
            f"http://127.0.0.1:{alpha.cdp_port}", timeout=30000
        ).contexts[0]

        page = _get_service_page(ctx, adapter)
        print("existing tab:", page.url)
        adapter.new_chat(page)
        page.reload(wait_until="domcontentloaded")
        page.wait_for_timeout(2000)
        before = adapter.count_responses(page)
        try_send("reload+send", page, adapter, before)

        page2 = ctx.new_page()
        adapter.new_chat(page2)
        before2 = adapter.count_responses(page2)
        try_send("new_page", page2, adapter, before2)


if __name__ == "__main__":
    main()
