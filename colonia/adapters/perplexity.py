from __future__ import annotations

from pathlib import Path

from playwright.sync_api import Page

from colonia.adapters.base import ChatAdapter, DomSelectors
from colonia.models import ServiceName, TaskStatus

BASE_URL = "https://www.perplexity.ai"


class PerplexityAdapter(ChatAdapter):
    service = ServiceName.PERPLEXITY
    start_url = f"{BASE_URL}/"
    selectors = DomSelectors(
        login_url_markers=("login-source", "auth.", "/login"),
        assistant_selector=(
            "[class*='prose'], [class*='markdown'], div[class*='answer'], main article"
        ),
        input_selector="textarea, div[contenteditable='true'], #ask-input",
    )

    def ensure_ready(self, page: Page) -> TaskStatus:
        url = (page.url or "").lower()
        if "login-source" in url or "auth.perplexity" in url:
            return TaskStatus.AUTH_REQUIRED
        if self.has_input(page):
            return TaskStatus.DONE
        if self._login_wall(page):
            return TaskStatus.AUTH_REQUIRED
        return TaskStatus.DONE

    def new_chat(self, page: Page) -> None:
        page.goto(f"{BASE_URL}/", wait_until="domcontentloaded", timeout=60000)
        page.wait_for_timeout(2000)

    def send(self, page: Page, prompt: str, files: list[Path] | None = None) -> None:
        if files:
            raise NotImplementedError("Perplexity file upload via adapter not yet implemented")
        super().send(page, prompt, files)
