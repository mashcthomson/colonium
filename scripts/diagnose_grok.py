#!/usr/bin/env python3
from playwright.sync_api import Page, sync_playwright

CDP = "http://127.0.0.1:9222"
PROMPT = "Reply with exactly one word: GROK_OK"

with sync_playwright() as pw:
    browser = pw.chromium.connect_over_cdp(CDP, timeout=30000)
    ctx = browser.contexts[0]
    page: Page | None = None
    for p in ctx.pages:
        if "grok.com" in (p.url or "") and "blob:" not in (p.url or ""):
            page = p
            break
    if not page:
        page = ctx.new_page()
    active_page = page
    active_page.goto("https://grok.com/", wait_until="domcontentloaded", timeout=60000)
    active_page.wait_for_timeout(2000)

    def dismiss_overlays():
        for label in [
            "Allow All",
            "Dismiss",
            "Hide upsell banner",
            "Close",
            "Not now",
            "Maybe later",
            "No thanks",
        ]:
            try:
                active_page.get_by_role("button", name=label).first.click(timeout=800)
                active_page.wait_for_timeout(300)
            except Exception:
                pass
        try:
            active_page.keyboard.press("Escape")
            active_page.wait_for_timeout(300)
        except Exception:
            pass

    dismiss_overlays()
    print("dialogs:", active_page.locator('[role="dialog"]').count())

    box = active_page.locator('[aria-label="Ask Grok anything"], [role="textbox"].tiptap').first
    box.click(timeout=15000, force=True)
    active_page.keyboard.press("Control+a")
    active_page.keyboard.press("Backspace")
    active_page.keyboard.type(PROMPT, delay=5)

    submit = active_page.locator('form button[type="submit"], button[type="submit"]').last
    print("submit count", submit.count())
    submit.click(timeout=5000, force=True)
    print("submitted, url:", active_page.url)

    texts: list[str] = []
    for i in range(45):
        active_page.wait_for_timeout(2000)
        snap = active_page.evaluate(
            """() => {
                const prose = [...document.querySelectorAll('.tiptap.ProseMirror, [class*="prose"], [class*="markdown"]')]
                    .map(n => (n.innerText||'').trim())
                    .filter(t => t.length > 0 && !t.includes('Ask Grok'));
                const streaming = !!document.querySelector('[aria-label*="Stop"]');
                return { streaming, prose, url: location.href };
            }"""
        )
        texts = snap["prose"]
        print(f"t={i * 2}s stream={snap['streaming']} blocks={len(texts)}")
        for t in texts[-2:]:
            if "GROK_OK" in t and PROMPT not in t:
                print("SUCCESS:", t[:200])
                print("URL:", snap["url"])
                raise SystemExit(0)

    print("FAILED - last blocks:", texts[-3:] if texts else [])
