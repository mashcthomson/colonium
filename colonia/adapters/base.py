from __future__ import annotations

from abc import ABC, abstractmethod
from dataclasses import dataclass
from pathlib import Path

from playwright.sync_api import Page

from colonia.models import ServiceName, TaskStatus
from colonia.placeholders import is_thinking_placeholder
from colonia.text import clean_model_label, normalize_response_markdown

BAD_URL_MARKERS = (
    "login",
    "signup",
    "sign-in",
    "settings",
    "personalization",
    "blob:",
    "stripe",
    "count.",
    "accounts.google.com",
)

DISMISS_BUTTON_LABELS = (
    "allow all",
    "accept all",
    "accept",
    "agree",
    "i agree",
    "got it",
    "ok",
    "okay",
    "dismiss",
    "close",
    "not now",
    "maybe later",
    "no thanks",
    "skip",
    "hide upsell banner",
    "hide banner",
)

DISMISS_ARIA_MARKERS = (
    "close",
    "dismiss",
    "hide upsell",
    "hide banner",
)

DISMISS_OVERLAY_JS = """({ labels, ariaMarkers }) => {
    // COLONIA_SAFE_DISMISS
    const normalizedLabels = new Set(labels);
    const markers = ariaMarkers.map((marker) => marker.toLowerCase());
    const normalize = (value) => (value || '').replace(/\\s+/g, ' ').trim().toLowerCase();
    const visible = (el) => {
        const style = window.getComputedStyle(el);
        const rect = el.getBoundingClientRect();
        return rect.width > 0
            && rect.height > 0
            && style.display !== 'none'
            && style.visibility !== 'hidden'
            && style.pointerEvents !== 'none';
    };
    const safeByName = (el) => {
        const text = normalize(el.innerText || el.textContent);
        const aria = normalize(el.getAttribute('aria-label'));
        const title = normalize(el.getAttribute('title'));
        if (normalizedLabels.has(text) || normalizedLabels.has(aria) || normalizedLabels.has(title)) {
            return true;
        }
        return markers.some((marker) => aria.includes(marker) || title.includes(marker));
    };
    const candidates = Array.from(document.querySelectorAll(
        'button, [role="button"], [aria-label], [title]'
    ));
    for (const el of candidates) {
        if (!visible(el) || !safeByName(el)) continue;
        el.click();
        return 1;
    }
    return 0;
}"""


@dataclass(frozen=True)
class DomSelectors:
    login_url_markers: tuple[str, ...]
    assistant_selector: str
    input_selector: str = "textarea, [contenteditable='true']"
    submit_selector: str = (
        'button[aria-label*="Submit"], button[data-testid*="submit"], '
        'form button[type="submit"], button[aria-label*="Send"], '
        'button[aria-label*="send"]'
    )
    stop_selector: str = (
        '[aria-label*="Stop"], [data-testid*="stop"], '
        '[aria-label*="stop generating"], button[aria-label*="Stop streaming"]'
    )
    send_key: str = "Enter"


class ChatAdapter(ABC):
    service: ServiceName
    start_url: str
    selectors: DomSelectors

    @abstractmethod
    def ensure_ready(self, page: Page) -> TaskStatus:
        """Return DONE if logged in, AUTH_REQUIRED if login wall detected."""

    def open_thread(self, page: Page, url: str) -> None:
        try:
            page.bring_to_front()
        except Exception:
            pass
        page.goto(url, wait_until="domcontentloaded", timeout=60000)
        page.wait_for_timeout(2000)
        self.dismiss_overlays(page)

    def new_chat(self, page: Page) -> None:
        try:
            page.bring_to_front()
        except Exception:
            pass
        page.goto(self.start_url, wait_until="domcontentloaded", timeout=60000)
        page.wait_for_timeout(2000)
        self.dismiss_overlays(page)

    def dismiss_overlays(self, page: Page, *, send_escape: bool = True) -> int:
        dismissed = 0
        for _ in range(4):
            try:
                clicked = int(
                    page.evaluate(
                        DISMISS_OVERLAY_JS,
                        {
                            "labels": DISMISS_BUTTON_LABELS,
                            "ariaMarkers": DISMISS_ARIA_MARKERS,
                        },
                    )
                    or 0
                )
            except Exception:
                clicked = 0
            if clicked <= 0:
                break
            dismissed += clicked
            try:
                page.wait_for_timeout(150)
            except Exception:
                pass
        if send_escape:
            try:
                page.keyboard.press("Escape")
            except Exception:
                pass
        return dismissed

    def count_responses(self, page: Page) -> int:
        return int(
            page.evaluate(
                """(sel) => {
                    const sels = sel.split(',').map(s => s.trim());
                    let n = 0;
                    for (const s of sels) n += document.querySelectorAll(s).length;
                    return n;
                }""",
                self.selectors.assistant_selector,
            )
        )

    def _find_input(self, page: Page):
        for sel in (s.strip() for s in self.selectors.input_selector.split(",")):
            loc = page.locator(sel).first
            try:
                if loc.count() == 0:
                    continue
                hidden = loc.evaluate(
                    "el => el.getAttribute('aria-hidden') === 'true' || el.offsetParent === null"
                )
                if hidden:
                    continue
                if loc.is_visible(timeout=2000):
                    return loc
            except Exception:
                continue
        return None

    def send(self, page: Page, prompt: str, files: list[Path] | None = None) -> None:
        if files:
            raise NotImplementedError(f"{self.service.value} file upload not yet implemented")
        try:
            page.bring_to_front()
        except Exception:
            pass
        self.dismiss_overlays(page)
        loc = self._find_input(page)
        if loc is None:
            raise RuntimeError(f"{self.service.value}: input not found")
        try:
            loc.click(timeout=15000)
        except Exception:
            self.dismiss_overlays(page)
            loc.click(timeout=15000, force=True)
        tag = loc.evaluate("el => el.tagName.toLowerCase()")
        if tag == "textarea":
            loc.fill(prompt)
        else:
            loc.press("Control+a")
            loc.press("Backspace")
            if self.service == ServiceName.CLAUDE:
                page.keyboard.type(prompt, delay=5)
            else:
                try:
                    page.keyboard.insert_text(prompt)
                except AttributeError:
                    page.keyboard.type(prompt, delay=5)
        page.wait_for_timeout(150)
        submitted = False
        for sel in (s.strip() for s in self.selectors.submit_selector.split(",")):
            btn = page.locator(sel).last
            try:
                if (
                    btn.count() > 0
                    and btn.is_visible(timeout=1000)
                    and btn.is_enabled(timeout=1000)
                ):
                    btn.click(timeout=5000, force=True)
                    submitted = True
                    break
            except Exception:
                continue
        if not submitted:
            page.keyboard.press(self.selectors.send_key)

    def prepare_prompt(self, page: Page, prompt: str) -> None:
        return None

    def _is_streaming(self, page: Page) -> bool:
        stop_sel = self.selectors.stop_selector
        return bool(
            page.evaluate(
                """(sel) => {
                    const sels = sel.split(',').map(s => s.trim());
                    for (const s of sels) {
                        if (document.querySelector(s)) return true;
                    }
                    return false;
                }""",
                stop_sel,
            )
        )

    def poll_response_ready(
        self,
        page: Page,
        baseline_count: int,
        last_text: str,
        stable_ticks: int,
        min_stable_ticks: int = 1,
    ) -> tuple[bool, str, int]:
        self.dismiss_overlays(page, send_escape=False)
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

    def wait_until_done(self, page: Page, timeout_ms: int, baseline_count: int = 0) -> None:
        import time

        deadline = time.time() + timeout_ms / 1000
        last_text = ""
        stable_ticks = 0
        while time.time() < deadline:
            ready, last_text, stable_ticks = self.poll_response_ready(
                page, baseline_count, last_text, stable_ticks
            )
            if ready:
                page.wait_for_timeout(1000)
                text, _ = self.extract_since(page, baseline_count)
                if not is_thinking_placeholder(text):
                    return
            time.sleep(0.5)
        text, _ = self.extract_since(page, baseline_count)
        if not is_thinking_placeholder(text) and text.strip():
            return
        raise TimeoutError(f"{self.service.value} response timed out")

    def extract(self, page: Page) -> tuple[str, str]:
        return self.extract_since(page, 0)

    def extract_since(self, page: Page, after_count: int) -> tuple[str, str]:
        text, model = page.evaluate(
            """({ sel, after }) => {
                const normalize = (value) => (value || '').replace(/\\n{3,}/g, '\\n\\n').trim();
                const codeLanguage = (el) => {
                    const code = el.querySelector('code');
                    const className = code ? (code.className || '') : '';
                    const match = className.match(/language-([A-Za-z0-9_-]+)/);
                    return match ? match[1] : '';
                };
                const inline = (node) => Array.from(node.childNodes).map((child) => {
                    if (child.nodeType === Node.TEXT_NODE) return child.textContent || '';
                    if (child.nodeType !== Node.ELEMENT_NODE) return '';
                    const tag = child.tagName.toLowerCase();
                    if (tag === 'br') return '\\n';
                    if (tag === 'code' && child.closest('pre') === null) {
                        return '`' + (child.innerText || child.textContent || '').trim() + '`';
                    }
                    if (tag === 'a') {
                        const text = normalize(child.innerText || child.textContent);
                        const href = child.getAttribute('href') || '';
                        return href && text && href !== text ? `${text} (${href})` : text;
                    }
                    return inline(child);
                }).join('');
                const nodeToMarkdown = (root) => {
                    const parts = [];
                    const visit = (el) => {
                        if (el.nodeType === Node.TEXT_NODE) {
                            const text = (el.textContent || '').trim();
                            if (text) parts.push(text);
                            return;
                        }
                        if (el.nodeType !== Node.ELEMENT_NODE) return;
                        const tag = el.tagName.toLowerCase();
                        if (tag === 'pre') {
                            const code = el.querySelector('code') || el;
                            const lang = codeLanguage(el);
                            parts.push(
                                '\\n\\n```' + lang + '\\n'
                                + (code.innerText || code.textContent || '').trimEnd()
                                + '\\n```\\n\\n'
                            );
                            return;
                        }
                        if (/^h[1-6]$/.test(tag)) {
                            const level = Number(tag.slice(1));
                            parts.push(`${'#'.repeat(level)} ${normalize(el.innerText || el.textContent)}\\n\\n`);
                            return;
                        }
                        if (tag === 'li') {
                            parts.push(`- ${normalize(inline(el))}\\n`);
                            return;
                        }
                        if (['p', 'div', 'section', 'article', 'blockquote'].includes(tag)) {
                            const hasBlockCode = !!el.querySelector(':scope > pre');
                            if (!hasBlockCode) {
                                const text = normalize(inline(el));
                                if (text) parts.push(text + '\\n\\n');
                                return;
                            }
                        }
                        Array.from(el.childNodes).forEach(visit);
                    };
                    visit(root);
                    return normalize(parts.join(''));
                };
                const sels = sel.split(',').map(s => s.trim());
                const nodes = [];
                for (const s of sels) {
                    document.querySelectorAll(s).forEach(n => nodes.push(n));
                }
                if (!nodes.length) return ['', ''];
                const start = Math.min(after, nodes.length);
                const slice = nodes.slice(start);
                const last = slice.length ? slice[slice.length - 1] : nodes[nodes.length - 1];
                const text = nodeToMarkdown(last) || (last.innerText || last.textContent || '').trim();
                const modelEl = document.querySelector('[data-testid*="model"], [class*="model"]');
                const model = modelEl ? (modelEl.textContent || '').trim() : '';
                return [text, model];
            }""",
            {"sel": self.selectors.assistant_selector, "after": after_count},
        )
        label = clean_model_label(model or self.service.value.title())
        return normalize_response_markdown(text or "", service=self.service.value), label

    def _login_wall(self, page: Page) -> bool:
        url = (page.url or "").lower()
        if any(m in url for m in self.selectors.login_url_markers):
            return True
        return any(
            m in url
            for m in BAD_URL_MARKERS
            if m in ("login", "signup", "sign-in", "accounts.google.com")
        )

    def has_input(self, page: Page) -> bool:
        self.dismiss_overlays(page)
        return self._find_input(page) is not None
