from __future__ import annotations

import time
from dataclasses import dataclass, field
from pathlib import Path

from playwright.sync_api import Page, sync_playwright

from colonia.adapters import get_adapter
from colonia.adapters.base import ChatAdapter
from colonia.models import BrowserInstance, CouncilResponse, ServiceName, TaskStatus
from colonia.prompt_profiles import apply_prompt_profile
from colonia.runner import _browser_by_name, _ensure_service_page_loaded, _open_task_page
from colonia.sessions import SessionStore
from colonia.text import normalize_response_markdown


@dataclass
class _WaveSlot:
    service: ServiceName
    adapter: ChatAdapter
    page: Page
    browser_name: str
    before_count: int
    sent_at: float = field(default_factory=time.time)
    last_text: str = ""
    stable_ticks: int = 0
    ready_at: float | None = None
    status: TaskStatus = TaskStatus.TYPING
    error: str | None = None
    model_label: str = ""


def run_browser_wave(
    *,
    browser: BrowserInstance,
    services: list[ServiceName],
    prompt: str,
    files: list[Path],
    fresh_chat: bool,
    session_id: str | None,
    timeout_ms: int,
    settle_ms: int = 8000,
    stable_polls: int = 2,
    session_store: SessionStore | None = None,
    artifact_root: Path | None = None,
) -> list[CouncilResponse]:
    """Send to every service tab in parallel, poll until done, then collect."""
    if not services:
        return []

    store = session_store or SessionStore()
    started = time.time()
    effective_browser = browser.name
    if session_id:
        effective_browser = store.resolve_browser(session_id, browser.name)
        browser = _browser_by_name(effective_browser) or browser

    cdp_url = f"http://127.0.0.1:{browser.cdp_port}"
    slots: list[_WaveSlot] = []

    with sync_playwright() as pw:
        chromium = pw.chromium.connect_over_cdp(cdp_url, timeout=30000)
        ctx = chromium.contexts[0] if chromium.contexts else chromium.new_context()

        for service in services:
            adapter = get_adapter(service)
            page = _open_task_page(
                ctx,
                adapter,
                session_id=session_id,
                fresh_chat=fresh_chat,
            )
            slot = _prepare_and_send(
                slot=_WaveSlot(
                    service=service,
                    adapter=adapter,
                    page=page,
                    browser_name=browser.name,
                    before_count=0,
                ),
                prompt=prompt,
                files=files,
                fresh_chat=fresh_chat,
                session_id=session_id,
                store=store,
            )
            slots.append(slot)

        _poll_until_ready(slots, timeout_ms, stable_polls)
        _apply_settle(slots, settle_ms)
        responses = _collect_slots(
            slots,
            store,
            session_id,
            browser.name,
            started,
            files,
            artifact_root,
        )

    return responses


def _prepare_and_send(
    *,
    slot: _WaveSlot,
    prompt: str,
    files: list[Path],
    fresh_chat: bool,
    session_id: str | None,
    store: SessionStore,
) -> _WaveSlot:
    adapter = slot.adapter
    page = slot.page

    try:
        initial_navigation = _ensure_service_page_loaded(page, adapter)
        status = adapter.ensure_ready(page)
        if status == TaskStatus.AUTH_REQUIRED:
            slot.status = TaskStatus.AUTH_REQUIRED
            slot.error = "Login required — open this browser on Colonia Desktop 2 and sign in"
            return slot

        if session_id and not fresh_chat:
            binding = store.get_binding(session_id, slot.browser_name, slot.service)
            if binding:
                adapter.open_thread(page, binding.thread_url)
            else:
                adapter.new_chat(page)
        else:
            if session_id and fresh_chat:
                store.delete_binding(session_id, slot.browser_name, slot.service)
            if not initial_navigation:
                adapter.new_chat(page)

        status = adapter.ensure_ready(page)
        if status == TaskStatus.AUTH_REQUIRED:
            slot.status = TaskStatus.AUTH_REQUIRED
            slot.error = "Login required after navigation"
            return slot

        slot.before_count = adapter.count_responses(page)
        prepared_prompt = apply_prompt_profile(
            prompt,
            browser=slot.browser_name,
            service=slot.service.value,
        )
        prepare_prompt = getattr(adapter, "prepare_prompt", None)
        if prepare_prompt:
            prepare_prompt(page, prepared_prompt)
        adapter.send(page, prepared_prompt, files or None)
        slot.sent_at = time.time()
        slot.status = TaskStatus.TYPING
    except NotImplementedError as e:
        slot.status = TaskStatus.SKIPPED
        slot.error = str(e)
    except Exception as e:
        slot.status = TaskStatus.ERROR
        slot.error = str(e)

    return slot


def _poll_until_ready(slots: list[_WaveSlot], timeout_ms: int, stable_polls: int) -> None:
    deadline = time.time() + timeout_ms / 1000
    poll_interval = 0.5

    while time.time() < deadline:
        all_done = True
        for slot in slots:
            if slot.status != TaskStatus.TYPING:
                continue
            all_done = False
            ready, text, ticks = slot.adapter.poll_response_ready(
                slot.page,
                slot.before_count,
                slot.last_text,
                slot.stable_ticks,
                stable_polls,
            )
            slot.last_text = text
            slot.stable_ticks = ticks
            if ready:
                slot.ready_at = time.time()
                slot.status = TaskStatus.DONE
        if all_done:
            return
        time.sleep(poll_interval)

    for slot in slots:
        if slot.status == TaskStatus.TYPING:
            slot.status = TaskStatus.TIMEOUT
            slot.error = f"{slot.service.value} response timed out"


def _apply_settle(slots: list[_WaveSlot], settle_ms: int) -> None:
    ready_times = [s.ready_at for s in slots if s.ready_at is not None]
    if not ready_times:
        return
    last_ready = max(ready_times)
    wait_until = last_ready + settle_ms / 1000
    remaining = wait_until - time.time()
    if remaining > 0:
        time.sleep(remaining)


def _collect_slots(
    slots: list[_WaveSlot],
    store: SessionStore,
    session_id: str | None,
    browser_name: str,
    started: float,
    files: list[Path],
    artifact_root: Path | None,
) -> list[CouncilResponse]:
    responses: list[CouncilResponse] = []
    for slot in slots:
        latency = int((time.time() - started) * 1000)

        if slot.status == TaskStatus.AUTH_REQUIRED:
            responses.append(
                CouncilResponse(
                    browser=browser_name,
                    service=slot.service.value,
                    status=TaskStatus.AUTH_REQUIRED,
                    url=slot.page.url,
                    latency_ms=latency,
                    error=slot.error,
                )
            )
            continue

        if slot.status in (TaskStatus.SKIPPED, TaskStatus.ERROR, TaskStatus.TIMEOUT):
            responses.append(
                CouncilResponse(
                    browser=browser_name,
                    service=slot.service.value,
                    status=slot.status,
                    url=slot.page.url,
                    latency_ms=latency,
                    error=slot.error,
                )
            )
            continue

        text, model_label = slot.adapter.extract_since(slot.page, slot.before_count)
        text = normalize_response_markdown(text, service=slot.service.value)
        after_count = slot.adapter.count_responses(slot.page)

        if not text.strip():
            responses.append(
                CouncilResponse(
                    browser=browser_name,
                    service=slot.service.value,
                    model_label=model_label,
                    status=TaskStatus.ERROR,
                    text="",
                    url=slot.page.url,
                    latency_ms=latency,
                    error="Empty response — check input selectors or login state",
                )
            )
            continue

        if session_id:
            store.save_binding(
                session_id,
                browser_name,
                slot.service,
                slot.page.url or slot.adapter.start_url,
                after_count,
            )

        response = CouncilResponse(
            browser=browser_name,
            service=slot.service.value,
            model_label=model_label,
            status=TaskStatus.DONE,
            text=text,
            url=slot.page.url,
            latency_ms=latency,
            attachments_sent=[str(f) for f in files] if files else [],
        )
        if artifact_root:
            from colonia.runner import _collect_response_artifacts

            response.artifacts_received = _collect_response_artifacts(
                slot.page,
                artifact_root=artifact_root,
                browser=browser_name,
                service=slot.service.value,
                text=text,
            )
        responses.append(response)

    return responses
