from __future__ import annotations

from pathlib import Path

from playwright.sync_api import Page

from colonium.adapters.base import ChatAdapter, DomSelectors
from colonium.models import ServiceName, TaskStatus
from colonium.placeholders import is_thinking_placeholder
from colonium.text import normalize_response_markdown


class GrokAdapter(ChatAdapter):
    service = ServiceName.GROK
    start_url = "https://grok.com/"
    selectors = DomSelectors(
        login_url_markers=("login", "sign-in", "x.com/i/flow"),
        assistant_selector="grok-response",
        input_selector='[aria-label="Ask Grok anything"]',
        submit_selector='form button[type="submit"], button[type="submit"]',
        stop_selector='[aria-label*="Stop"], button[aria-label*="stop"]',
        send_key="Enter",
    )

    def ensure_ready(self, page: Page) -> TaskStatus:
        if self._login_wall(page):
            return TaskStatus.AUTH_REQUIRED
        self.dismiss_overlays(page)
        return TaskStatus.DONE if self.has_input(page) else TaskStatus.AUTH_REQUIRED

    def new_chat(self, page: Page) -> None:
        page.goto(self.start_url, wait_until="domcontentloaded", timeout=60000)
        page.wait_for_timeout(2000)
        self.dismiss_overlays(page)

    def open_thread(self, page: Page, url: str) -> None:
        page.goto(url, wait_until="domcontentloaded", timeout=60000)
        page.wait_for_timeout(2000)
        self.dismiss_overlays(page)

    def _find_input(self, page: Page):
        loc = page.locator(self.selectors.input_selector).first
        try:
            if loc.count() > 0:
                return loc
        except Exception:
            pass
        return page.locator("[role='textbox'].tiptap").first

    def send(self, page: Page, prompt: str, files: list[Path] | None = None) -> None:
        if files:
            raise NotImplementedError("Grok file upload not yet implemented")
        self.dismiss_overlays(page)
        loc = self._find_input(page)
        if loc is None or loc.count() == 0:
            raise RuntimeError("grok: input not found")
        loc.click(timeout=15000, force=True)
        page.keyboard.press("Control+a")
        page.keyboard.press("Backspace")
        try:
            page.keyboard.insert_text(prompt)
        except AttributeError:
            page.keyboard.type(prompt, delay=5)
        submit = page.locator(self.selectors.submit_selector).last
        if submit.count() == 0:
            raise RuntimeError("grok: submit button not found")
        submit.click(timeout=5000, force=True)

    def count_responses(self, page: Page) -> int:
        return int(page.evaluate(_COUNT_RESPONSES_JS))

    def extract_since(self, page: Page, after_count: int) -> tuple[str, str]:
        text, model = page.evaluate(_EXTRACT_RESPONSES_JS, after_count)
        label = model or "Grok"
        return normalize_response_markdown(text or "", service=self.service.value), label

    def poll_response_ready(
        self,
        page: Page,
        baseline_count: int,
        last_text: str,
        stable_ticks: int,
        min_stable_ticks: int = 1,
    ) -> tuple[bool, str, int]:
        count = self.count_responses(page)
        if count <= baseline_count:
            return False, last_text, 0

        text, _ = self.extract_since(page, baseline_count)
        if is_thinking_placeholder(text):
            return False, text, 0
        if self._is_streaming(page):
            return False, text, 0

        if text == last_text:
            stable_ticks += 1
        else:
            stable_ticks = 0
        if stable_ticks >= min_stable_ticks:
            return True, text, stable_ticks
        return False, text, stable_ticks


_IS_THINKING_JS = """(t) => {
    const l = (t || '').toLowerCase().trim();
    if (l.length < 4) return true;
    if (/^thinking/.test(l) && l.length < 100) return true;
    if (/thinking about/.test(l)) return true;
    return false;
}"""

_COUNT_RESPONSES_JS = (
    """() => {
    const isThinking = """
    + _IS_THINKING_JS
    + """;
    const nodes = [];
    document.querySelectorAll('[class*="prose"], [class*="markdown"], article').forEach(el => {
        if (el.getAttribute('contenteditable') === 'true') return;
        if (el.getAttribute('aria-label') === 'Ask Grok anything') return;
        if (el.closest('[aria-label="Ask Grok anything"]')) return;
        const t = (el.innerText || '').trim();
        if (t.length > 0 && !isThinking(t)) nodes.push(el);
    });
    return nodes.length;
}"""
)

_EXTRACT_RESPONSES_JS = (
    """(after) => {
    const isThinking = """
    + _IS_THINKING_JS
    + """;
    const nodes = [];
    document.querySelectorAll('[class*="prose"], [class*="markdown"], article').forEach(el => {
        if (el.getAttribute('contenteditable') === 'true') return;
        if (el.getAttribute('aria-label') === 'Ask Grok anything') return;
        if (el.closest('[aria-label="Ask Grok anything"]')) return;
        const t = (el.innerText || '').trim();
        if (t.length > 0 && !isThinking(t)) nodes.push(el);
    });
    if (!nodes.length) return ['', ''];
    const start = Math.min(after, nodes.length);
    const slice = nodes.slice(start);
    let last = null;
    for (let i = slice.length - 1; i >= 0; i--) {
        const t = (slice[i].innerText || slice[i].textContent || '').trim();
        if (t && !isThinking(t)) { last = slice[i]; break; }
    }
    if (!last) last = nodes[nodes.length - 1];
    const text = (last.innerText || last.textContent || '').trim();
    const modelBtn = document.querySelector('button[aria-label="Model select"]');
    const model = modelBtn ? (modelBtn.textContent || '').trim() : 'Grok';
    return [text, model];
}"""
)
