from __future__ import annotations

from pathlib import Path

from playwright.sync_api import Page

from colonium.adapters.base import ChatAdapter, DomSelectors
from colonium.models import ServiceName, TaskStatus
from colonium.text import normalize_response_markdown


DEEP_RESEARCH_TRIGGERS = (
    "#deep-research",
    "#chatgpt-tool:deep-research",
    "deep research",
    "deeply research",
    "comprehensive research",
    "thorough research",
    "research report",
)

WEB_SEARCH_TRIGGERS = (
    "#web-search",
    "#chatgpt-tool:web-search",
    "web search",
    "latest",
    "current",
    "today",
    "this week",
    "as of now",
)

NO_TOOL_TRIGGERS = (
    "#chatgpt-tool:none",
    "#no-chatgpt-tool",
)


def choose_chatgpt_tool(prompt: str) -> str | None:
    lowered = prompt.lower()
    if any(trigger in lowered for trigger in NO_TOOL_TRIGGERS):
        return None
    if any(trigger in lowered for trigger in DEEP_RESEARCH_TRIGGERS):
        return "Deep research"
    if any(trigger in lowered for trigger in WEB_SEARCH_TRIGGERS):
        return "Web search"
    return None


class ChatGPTAdapter(ChatAdapter):
    service = ServiceName.CHATGPT
    start_url = "https://chatgpt.com/"
    selectors = DomSelectors(
        login_url_markers=("auth.openai.com", "/login", "signin"),
        assistant_selector=(
            "[data-message-author-role='assistant'], "
            "div[data-message-author-role='assistant'] .markdown"
        ),
        input_selector="#prompt-textarea, textarea[data-id], textarea",
    )

    def ensure_ready(self, page: Page) -> TaskStatus:
        if self._login_wall(page):
            return TaskStatus.AUTH_REQUIRED
        return TaskStatus.DONE if self.has_input(page) else TaskStatus.AUTH_REQUIRED

    def prepare_prompt(self, page: Page, prompt: str) -> None:
        tool = choose_chatgpt_tool(prompt)
        if tool:
            _select_chatgpt_tool(page, tool)


class ClaudeAdapter(ChatAdapter):
    service = ServiceName.CLAUDE
    start_url = "https://claude.ai/new"
    selectors = DomSelectors(
        login_url_markers=("claude.ai/login", "/login"),
        assistant_selector=(
            "[data-testid='assistant-message'], .font-claude-message, div[data-is-streaming]"
        ),
        input_selector="div.ProseMirror[contenteditable='true'], div[contenteditable='true']",
        submit_selector=(
            'button[aria-label="Send message"], '
            'button[aria-label*="Send"], button[aria-label*="send"]'
        ),
        send_key="Enter",
    )

    def ensure_ready(self, page: Page) -> TaskStatus:
        if self._login_wall(page):
            return TaskStatus.AUTH_REQUIRED
        return TaskStatus.DONE if self.has_input(page) else TaskStatus.AUTH_REQUIRED

    def send(self, page: Page, prompt: str, files: list[Path] | None = None) -> None:
        if files:
            raise NotImplementedError("Claude file upload not yet implemented")
        try:
            page.bring_to_front()
        except Exception:
            pass
        self.dismiss_overlays(page)
        loc = self._find_input(page)
        if loc is None:
            raise RuntimeError("claude: input not found")
        try:
            loc.click(timeout=15000)
        except Exception:
            self.dismiss_overlays(page)
            loc.click(timeout=15000, force=True)
        loc.press("Control+a")
        loc.press("Backspace")
        try:
            page.keyboard.insert_text(prompt)
        except AttributeError:
            page.keyboard.type(prompt, delay=5)
        page.wait_for_timeout(300)
        composer_text = (loc.inner_text(timeout=2000) or "").strip()
        if not composer_text:
            try:
                page.keyboard.type(prompt, delay=5)
            except Exception:
                pass
        submitted = False
        for sel in (
            'button[aria-label="Send message"]',
            'button[aria-label*="Send"]',
            'button[aria-label*="send"]',
        ):
            submit = page.locator(sel).last
            try:
                if (
                    submit.count() > 0
                    and submit.is_visible(timeout=1000)
                    and submit.is_enabled(timeout=1000)
                ):
                    submit.click(timeout=5000, force=True)
                    submitted = True
                    break
            except Exception:
                continue
        if not submitted:
            page.keyboard.press("Enter")

    def count_responses(self, page: Page) -> int:
        return int(page.evaluate(_CLAUDE_COUNT_JS))

    def extract_since(self, page: Page, after_count: int) -> tuple[str, str]:
        text, model = page.evaluate(_CLAUDE_EXTRACT_JS, after_count)
        return normalize_response_markdown(
            text or "", service=self.service.value
        ), model or "Claude"


_CLAUDE_COUNT_JS = """() => {
    const headings = Array.from(document.querySelectorAll('h2.sr-only')).filter((el) =>
        (el.innerText || el.textContent || '').trim().startsWith('Claude responded:')
    );
    if (headings.length) return headings.length;
    return document.querySelectorAll(
        "[data-testid='assistant-message'], .font-claude-message, div[data-is-streaming]"
    ).length;
}"""

_CLAUDE_EXTRACT_JS = """(after) => {
    const modelText = () => {
        const candidates = Array.from(document.querySelectorAll('button, div, span'));
        for (const el of candidates) {
            const text = (el.innerText || el.textContent || '').trim();
            if (/^Sonnet|^Opus|^Haiku/.test(text)) return text;
        }
        return 'Claude';
    };
    const normalize = (value) => (value || '').replace(/\\n{3,}/g, '\\n\\n').trim();
    const responseNodes = () => {
        const headings = Array.from(document.querySelectorAll('h2.sr-only')).filter((el) =>
            (el.innerText || el.textContent || '').trim().startsWith('Claude responded:')
        );
        if (headings.length) {
            return headings.map((heading) => {
                return (
                    heading.closest('div[data-is-streaming]')
                    || heading.parentElement
                    || heading
                );
            });
        }
        return Array.from(document.querySelectorAll(
            "[data-testid='assistant-message'], .font-claude-message, div[data-is-streaming]"
        ));
    };
    const nodes = responseNodes();
    if (!nodes.length) return ['', modelText()];
    const start = Math.min(after, nodes.length);
    const slice = nodes.slice(start);
    const last = slice.length ? slice[slice.length - 1] : nodes[nodes.length - 1];
    let text = normalize(last.innerText || last.textContent || '');
    const prefix = /^Claude responded:[^\\n]*\\n*/i;
    if (prefix.test(text)) {
        const stripped = normalize(text.replace(prefix, ''));
        if (stripped) text = stripped;
    }
    return [text, modelText()];
}"""


_GEMINI_COUNT_JS = """() => document.querySelectorAll('message-content').length"""

_GEMINI_EXTRACT_JS = """(after) => {
    const nodes = [...document.querySelectorAll('message-content')];
    if (!nodes.length) return ['', ''];
    const start = Math.min(after, nodes.length);
    const slice = nodes.slice(start);
    const pick = slice.length ? slice : nodes;
    const codeBlocksToMarkdown = (node) => {
        const blocks = [...node.querySelectorAll('code-block')];
        if (!blocks.length) return '';
        return blocks.map((block) => {
            const lines = (block.innerText || block.textContent || '').split('\\n');
            const lang = (lines.shift() || '').trim().toLowerCase();
            const code = lines.join('\\n').trimEnd();
            if (!code.trim()) return '';
            return '```' + lang + '\\n' + code + '\\n```';
        }).filter(Boolean).join('\\n\\n');
    };
    for (let i = pick.length - 1; i >= 0; i--) {
        const md = codeBlocksToMarkdown(pick[i]);
        if (md) return [md, 'Gemini'];
        const t = (pick[i].innerText || pick[i].textContent || '').trim();
        if (t.length > 0) return [t, 'Gemini'];
    }
    const last = nodes[nodes.length - 1];
    const md = codeBlocksToMarkdown(last);
    if (md) return [md, 'Gemini'];
    return [(last.innerText || last.textContent || '').trim(), 'Gemini'];
}"""


class GeminiAdapter(ChatAdapter):
    service = ServiceName.GEMINI
    start_url = "https://gemini.google.com/app"
    selectors = DomSelectors(
        login_url_markers=("accounts.google.com/signin", "ServiceLogin"),
        assistant_selector="message-content",
        input_selector="rich-textarea div[contenteditable='true'], div.ql-editor",
        submit_selector=(
            'button[aria-label*="Send"], button[mattooltip*="Send"], '
            'button.send-button, button[aria-label*="submit"]'
        ),
        stop_selector=('[aria-label*="Stop"], [data-testid*="stop"], button[aria-label*="Cancel"]'),
        send_key="Enter",
    )

    def _activate(self, page: Page) -> None:
        page.bring_to_front()

    def ensure_ready(self, page: Page) -> TaskStatus:
        self._activate(page)
        if self._login_wall(page):
            return TaskStatus.AUTH_REQUIRED
        return TaskStatus.DONE if self.has_input(page) else TaskStatus.AUTH_REQUIRED

    def new_chat(self, page: Page) -> None:
        self._activate(page)
        page.goto(self.start_url, wait_until="domcontentloaded", timeout=60000)
        page.wait_for_timeout(1500)
        self.dismiss_overlays(page)
        # Reused tabs on /app can keep stale SPA state; reload resets the composer.
        page.reload(wait_until="domcontentloaded")
        page.wait_for_timeout(2000)
        self.dismiss_overlays(page)

    def open_thread(self, page: Page, url: str) -> None:
        self._activate(page)
        page.goto(url, wait_until="domcontentloaded", timeout=60000)
        page.wait_for_timeout(2000)
        self.dismiss_overlays(page)

    def send(self, page: Page, prompt: str, files: list[Path] | None = None) -> None:
        if files:
            raise NotImplementedError("Gemini file upload not yet implemented")
        self._activate(page)
        self.dismiss_overlays(page)
        loc = self._find_input(page)
        if loc is None:
            raise RuntimeError("gemini: input not found")
        loc.click(timeout=15000)
        loc.press("Control+a")
        loc.press("Backspace")
        try:
            page.keyboard.insert_text(prompt)
        except AttributeError:
            page.keyboard.type(prompt, delay=5)
        submitted = False
        for sel in (s.strip() for s in self.selectors.submit_selector.split(",")):
            btn = page.locator(sel).first
            try:
                if btn.count() > 0 and btn.is_enabled(timeout=1000):
                    btn.click(timeout=5000)
                    submitted = True
                    break
            except Exception:
                continue
        if not submitted:
            page.keyboard.press(self.selectors.send_key)

    def count_responses(self, page: Page) -> int:
        return int(page.evaluate(_GEMINI_COUNT_JS))

    def extract_since(self, page: Page, after_count: int) -> tuple[str, str]:
        text, model = page.evaluate(_GEMINI_EXTRACT_JS, after_count)
        return normalize_response_markdown(
            text or "", service=self.service.value
        ), model or "Gemini"


def _select_chatgpt_tool(page: Page, label: str) -> None:
    page.locator("[data-testid='composer-plus-btn']").first.click(timeout=10_000, force=True)
    page.wait_for_timeout(500)
    option = page.get_by_text(label, exact=True).first
    option.wait_for(state="visible", timeout=10_000)
    option.click(timeout=10_000, force=True)
    page.wait_for_timeout(500)
