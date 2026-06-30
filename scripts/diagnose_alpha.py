#!/usr/bin/env python3
"""Diagnose DOM on alpha browser tabs."""

from playwright.sync_api import sync_playwright

CDP = "http://127.0.0.1:9222"

CHECKS = {
    "chatgpt.com": {
        "url": "https://chatgpt.com",
        "input": "#prompt-textarea, textarea[data-id], textarea",
        "assistant": "[data-message-author-role='assistant']",
    },
    "claude.ai": {
        "url": "https://claude.ai/new",
        "input": "div[contenteditable='true'], textarea",
        "assistant": "[data-is-streaming], .font-claude-message, [data-testid='conversation-turn']",
    },
    "gemini.google.com": {
        "url": "https://gemini.google.com/app",
        "input": "rich-textarea, div.ql-editor, [contenteditable='true']",
        "assistant": "message-content, .response-content, model-response",
    },
    "grok.com": {
        "url": "https://grok.com",
        "input": "textarea, [contenteditable='true'], [data-testid='query-input']",
        "assistant": "[class*='message'], article",
    },
    "perplexity.ai": {
        "url": "https://www.perplexity.ai",
        "input": "textarea, [contenteditable='true']",
        "assistant": "[class*='markdown'], main article",
    },
}


def main():
    with sync_playwright() as pw:
        browser = pw.chromium.connect_over_cdp(CDP, timeout=30000)
        ctx = browser.contexts[0]
        print("Pages open:", len(ctx.pages))
        for p in ctx.pages:
            print(" -", (p.url or "")[:100])

        for host, cfg in CHECKS.items():
            print(f"\n=== {host} ===")
            page = None
            for p in ctx.pages:
                if host in (p.url or ""):
                    page = p
                    break
            if not page:
                page = ctx.new_page()
            page.goto(cfg["url"], wait_until="domcontentloaded", timeout=60000)
            page.wait_for_timeout(3000)
            print("URL:", page.url[:90])
            for label, sel in [("input", cfg["input"]), ("assistant", cfg["assistant"])]:
                n = page.evaluate(
                    """(sel) => {
                        const sels = sel.split(',').map(s => s.trim());
                        let n = 0;
                        for (const s of sels) { n += document.querySelectorAll(s).length; }
                        return n;
                    }""",
                    sel,
                )
                print(f"  {label} count ({sel[:40]}...): {n}")


if __name__ == "__main__":
    main()
