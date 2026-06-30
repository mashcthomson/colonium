from __future__ import annotations

import argparse
import os
import sys
import types
from pathlib import Path
from typing import Any, cast

import pytest

from colonium.adapters.base import ChatAdapter, DomSelectors
from colonium.adapters.dom import GeminiAdapter
from colonium.adapters.grok import GrokAdapter
from colonium.adapters.perplexity import PerplexityAdapter
from colonium.config import default_config
from colonium.models import (
    ArtifactRecord,
    BrowserInstance,
    CouncilJobRequest,
    CouncilResponse,
    DesktopMode,
    ServiceName,
    TaskStatus,
)


class MinimalAdapter(ChatAdapter):
    service = ServiceName.CHATGPT
    start_url = "https://chatgpt.com/"
    selectors = DomSelectors(
        login_url_markers=("login",),
        assistant_selector=".assistant",
        input_selector="div[contenteditable='true'], textarea",
        submit_selector="button[type='submit']",
        stop_selector=".stop",
    )

    def ensure_ready(self, page: Any) -> TaskStatus:
        return TaskStatus.DONE if self.has_input(page) else TaskStatus.AUTH_REQUIRED


class KeyboardSpy:
    def __init__(self) -> None:
        self.presses: list[str] = []
        self.typed: list[str] = []
        self.inserted: list[str] = []

    def press(self, key: str) -> None:
        self.presses.append(key)

    def type(self, text: str, delay: int = 0) -> None:
        self.typed.append(text)

    def insert_text(self, text: str) -> None:
        self.inserted.append(text)


class LocatorSpy:
    def __init__(
        self,
        *,
        count: int = 1,
        visible: bool = True,
        enabled: bool = True,
        tag: str = "textarea",
        text: str = "",
        attr: str | None = None,
        fail_wait: bool = False,
    ) -> None:
        self._count = count
        self._visible = visible
        self._enabled = enabled
        self._tag = tag
        self._text = text
        self._attr = attr
        self.fail_wait = fail_wait
        self.clicks: list[dict[str, Any]] = []
        self.fills: list[str] = []
        self.presses: list[str] = []

    @property
    def first(self) -> "LocatorSpy":
        return self

    @property
    def last(self) -> "LocatorSpy":
        return self

    def count(self) -> int:
        return self._count

    def evaluate(self, script: str) -> Any:
        if "tagName" in script:
            return self._tag
        return not self._visible

    def is_visible(self, timeout: int = 0) -> bool:
        return self._visible

    def is_enabled(self, timeout: int = 0) -> bool:
        return self._enabled

    def click(self, timeout: int = 0, force: bool = False) -> None:
        self.clicks.append({"timeout": timeout, "force": force})

    def fill(self, text: str) -> None:
        self.fills.append(text)

    def press(self, key: str) -> None:
        self.presses.append(key)

    def wait_for(self, state: str = "visible", timeout: int = 0) -> None:
        if self.fail_wait:
            raise RuntimeError("not visible")

    def filter(self, has_text: str) -> "LocatorSpy":
        return self

    def get_attribute(self, name: str) -> str | None:
        return self._attr

    def inner_text(self, timeout: int = 0) -> str:
        if self.fail_wait:
            raise RuntimeError("no body")
        return self._text


class AdapterPage:
    def __init__(self) -> None:
        self.url = "https://chatgpt.com/c/1"
        self.keyboard = KeyboardSpy()
        self.input = LocatorSpy(tag="div")
        self.submit = LocatorSpy()
        self.gotos: list[str] = []
        self.waits: list[int] = []
        self.dismiss_calls = 0
        self.streaming = False
        self.response_count = 2
        self.extract_text = "answer"

    def goto(self, url: str, wait_until: str, timeout: int) -> None:
        self.gotos.append(url)
        self.url = url

    def wait_for_timeout(self, ms: int) -> None:
        self.waits.append(ms)

    def evaluate(self, script: str, arg: Any = None) -> Any:
        if "COLONIUM_SAFE_DISMISS" in script:
            self.dismiss_calls += 1
            return 1 if self.dismiss_calls == 1 else 0
        if "document.querySelector(s)" in script:
            return self.streaming
        if "message-content').length" in script:
            return self.response_count
        if "return nodes.length" in script:
            return self.response_count
        if "Model select" in script:
            return [self.extract_text, "Grok"]
        if "message-content" in script:
            return [self.extract_text, "Gemini"]
        if "querySelectorAll(s).length" in script:
            return self.response_count
        if "modelEl" in script:
            return [self.extract_text, "Test Model"]
        raise AssertionError(f"unexpected script: {script[:80]}")

    def locator(self, selector: str) -> LocatorSpy:
        if "button" in selector:
            return self.submit
        return self.input

    def bring_to_front(self) -> None:
        return None

    def reload(self, wait_until: str) -> None:
        self.waits.append(0)


def test_base_adapter_navigation_send_extract_and_poll() -> None:
    adapter = MinimalAdapter()
    page = AdapterPage()

    adapter.open_thread(cast(Any, page), "https://chatgpt.com/c/thread")
    adapter.new_chat(cast(Any, page))
    adapter.send(cast(Any, page), "hello")

    assert page.gotos == ["https://chatgpt.com/c/thread", "https://chatgpt.com/"]
    assert page.keyboard.inserted == ["hello"]
    assert page.keyboard.typed == []
    assert page.submit.clicks
    assert adapter.count_responses(cast(Any, page)) == 2
    assert adapter.extract_since(cast(Any, page), 1) == ("answer", "Test Model")
    assert adapter.poll_response_ready(cast(Any, page), 1, "old", 0)[0] is False
    assert adapter.poll_response_ready(cast(Any, page), 1, "answer", 1)[0] is True


def test_base_adapter_wait_until_done_and_file_rejection() -> None:
    class DoneAdapter(MinimalAdapter):
        def poll_response_ready(self, *args: Any, **kwargs: Any) -> tuple[bool, str, int]:
            return True, "done", 1

        def extract_since(self, page: Any, after_count: int) -> tuple[str, str]:
            return "done", "Model"

    adapter = DoneAdapter()
    page = AdapterPage()

    adapter.wait_until_done(cast(Any, page), timeout_ms=10)

    with pytest.raises(NotImplementedError):
        adapter.send(cast(Any, page), "hello", [Path("input.txt")])


def test_service_adapters_cover_ready_and_send_paths(monkeypatch: pytest.MonkeyPatch) -> None:
    page = AdapterPage()
    page.url = "https://www.perplexity.ai/"
    perplexity = PerplexityAdapter()
    monkeypatch.setattr(perplexity, "has_input", lambda page: True)

    assert perplexity.ensure_ready(cast(Any, page)) == TaskStatus.DONE
    page.url = "https://www.perplexity.ai/login-source"
    assert perplexity.ensure_ready(cast(Any, page)) == TaskStatus.AUTH_REQUIRED
    with pytest.raises(NotImplementedError):
        perplexity.send(cast(Any, page), "prompt", [Path("file.pdf")])

    gemini = GeminiAdapter()
    gemini_page = AdapterPage()
    gemini_page.input = LocatorSpy(tag="div")
    gemini_page.submit = LocatorSpy()
    gemini.new_chat(cast(Any, gemini_page))
    gemini.open_thread(cast(Any, gemini_page), "https://gemini.google.com/app/thread")
    gemini.send(cast(Any, gemini_page), "hi")

    assert gemini_page.gotos[-1] == "https://gemini.google.com/app/thread"
    assert "hi" in gemini_page.keyboard.inserted


def test_grok_adapter_send_extract_and_poll() -> None:
    page = AdapterPage()
    page.url = "https://grok.com/"
    page.input = LocatorSpy(tag="div")
    page.submit = LocatorSpy()
    adapter = GrokAdapter()

    adapter.new_chat(cast(Any, page))
    adapter.open_thread(cast(Any, page), "https://grok.com/c/thread")
    adapter.send(cast(Any, page), "grok prompt")

    assert page.keyboard.inserted == ["grok prompt"]
    assert page.keyboard.typed == []
    assert adapter.count_responses(cast(Any, page)) == 2
    assert adapter.extract_since(cast(Any, page), 1) == ("answer", "Grok")


def test_runner_tab_helpers_close_duplicates() -> None:
    from colonium.adapters.dom import ChatGPTAdapter
    from colonium.runner import (
        _close_duplicate_service_tabs,
        _ensure_service_page_loaded,
        _is_service_tab,
        _is_start_page,
        _is_usable_tab,
        _normalized_host,
        _prefer_thread_pages,
    )

    class PageStub:
        def __init__(self, url: str, fail_close: bool = False) -> None:
            self.url = url
            self.closed = False
            self.fail_close = fail_close

        def close(self) -> None:
            if self.fail_close:
                raise RuntimeError("already gone")
            self.closed = True

    pages = [
        PageStub("https://chatgpt.com/"),
        PageStub("https://chatgpt.com/c/thread"),
        PageStub("https://chatgpt.com/settings", fail_close=True),
    ]
    ctx = types.SimpleNamespace(pages=pages)
    adapter = ChatGPTAdapter()

    assert _normalized_host("https://www.chatgpt.com/path") == "chatgpt.com"
    assert _is_service_tab("https://chatgpt.com/c/thread", "chatgpt.com")
    assert _is_start_page("https://chatgpt.com/", adapter.start_url)
    assert not _is_usable_tab("https://chatgpt.com/login", "chatgpt.com")
    assert _prefer_thread_pages(pages, adapter)[0].url == "https://chatgpt.com/c/thread"

    _close_duplicate_service_tabs(ctx, adapter, pages[1])
    assert pages[0].closed is True

    class LoadAdapter:
        start_url = "https://chat.example/"

        def __init__(self) -> None:
            self.new_chat_calls = 0

        def new_chat(self, page: PageStub) -> None:
            self.new_chat_calls += 1
            page.url = self.start_url

    load_adapter = LoadAdapter()
    blank = PageStub("about:blank")
    assert _ensure_service_page_loaded(blank, load_adapter) is True
    assert blank.url == "https://chat.example/"
    assert load_adapter.new_chat_calls == 1
    assert _ensure_service_page_loaded(blank, load_adapter) is False
    assert load_adapter.new_chat_calls == 1


def test_browser_launcher_reuses_existing_and_reports_health(tmp_path: Path) -> None:
    from colonium.browser.launcher import BrowserLauncher

    cfg = default_config()
    cfg.data_dir = tmp_path
    browser = cfg.browsers[0]
    launcher = BrowserLauncher(cfg)
    launcher._write_pid(browser, 1234)
    launcher.is_cdp_alive = lambda port: True  # type: ignore[method-assign]

    launched = launcher.launch_one(browser)

    assert launched.pid == 1234
    assert launched.cdp_url.endswith(str(browser.cdp_port))
    assert launcher.health()[0]["cdp_alive"] is True


def test_default_desktop_config_uses_current_mode_off_linux(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from colonium import models

    monkeypatch.setattr(models.sys, "platform", "darwin")

    cfg = models.DesktopConfig()

    assert cfg.mode == DesktopMode.CURRENT
    assert cfg.chrome_binary.endswith("Google Chrome")


def test_desktop_manager_factory_uses_current_manager_off_linux(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    from colonium.desktop.manager import CurrentDesktopManager, create_desktop_manager

    cfg = default_config()
    cfg.data_dir = tmp_path
    cfg.desktop.mode = DesktopMode.CURRENT
    monkeypatch.setattr("colonium.desktop.manager.sys.platform", "darwin")
    monkeypatch.delenv("DISPLAY", raising=False)

    mgr = create_desktop_manager(cfg)
    state = mgr.start()

    assert isinstance(mgr, CurrentDesktopManager)
    assert state.mode == DesktopMode.CURRENT
    assert "DISPLAY" not in mgr.browser_env()
    assert mgr.status()["running"] is True


def test_current_desktop_manager_rejects_linux_only_modes(tmp_path: Path) -> None:
    from colonium.desktop.manager import CurrentDesktopManager

    cfg = default_config()
    cfg.data_dir = tmp_path
    cfg.desktop.mode = DesktopMode.XEPHYR
    mgr = CurrentDesktopManager(cfg)

    with pytest.raises(RuntimeError, match="only supported on Linux"):
        mgr.start()


def test_browser_launcher_launch_stop_and_cdp_probe(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    from colonium.browser.launcher import BrowserLauncher

    cfg = default_config()
    cfg.data_dir = tmp_path
    cfg.desktop.mode = DesktopMode.WORKSPACE
    launcher = BrowserLauncher(cfg)
    alive_checks = [False, True]
    launcher.is_cdp_alive = lambda port: alive_checks.pop(0) if alive_checks else True  # type: ignore[method-assign]
    moved: list[int] = []
    launcher._move_to_workspace = moved.append  # type: ignore[method-assign]

    class Proc:
        pid = 4321
        returncode = None

        def poll(self) -> None:
            return None

    popen_calls: list[list[str]] = []

    def fake_popen(cmd: list[str], **kwargs: Any) -> Proc:
        popen_calls.append(cmd)
        return Proc()

    monkeypatch.setattr("subprocess.Popen", fake_popen)
    monkeypatch.setattr(launcher.desktop, "browser_env", lambda: {"DISPLAY": ":20"})

    launched = launcher.launch_one(cfg.browsers[0], open_urls=["https://example.test"], force=True)

    assert launched.pid == 4321
    assert popen_calls[0][-1] == "https://example.test"
    assert moved == [4321]

    monkeypatch.setattr(os, "getpgid", lambda pid: pid)
    killed: list[int] = []
    monkeypatch.setattr(os, "killpg", lambda pgid, sig: killed.append(pgid))

    assert launcher.stop_all() == 1
    assert killed == [4321]


def test_browser_launcher_errors_and_cdp_status(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    from colonium.browser.launcher import BrowserLauncher

    cfg = default_config()
    cfg.data_dir = tmp_path
    launcher = BrowserLauncher(cfg)
    disabled = cfg.browsers[0].model_copy(update={"enabled": False})

    with pytest.raises(ValueError):
        launcher.launch_one(disabled)

    class Response:
        status = 200

        def read(self) -> bytes:
            return b"{}"

    class Connection:
        def request(self, method: str, path: str) -> None:
            return None

        def getresponse(self) -> Response:
            return Response()

        def close(self) -> None:
            return None

    monkeypatch.setattr("http.client.HTTPConnection", lambda *args, **kwargs: Connection())
    assert launcher.is_cdp_alive(9222)

    class ClosedConnection(Connection):
        def request(self, method: str, path: str) -> None:
            raise OSError("closed")

    monkeypatch.setattr("http.client.HTTPConnection", lambda *args, **kwargs: ClosedConnection())
    assert not launcher.is_cdp_alive(9222)
    assert not launcher.is_cdp_alive(70000)


def test_desktop_manager_modes_and_status(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    from colonium.desktop.linux import DesktopState, LinuxDesktopManager

    cfg = default_config()
    cfg.data_dir = tmp_path
    cfg.desktop.mode = DesktopMode.CURRENT
    monkeypatch.setenv("DISPLAY", ":77")
    mgr = LinuxDesktopManager(cfg)
    monkeypatch.setattr(mgr, "is_display_alive", lambda display: True)

    state = mgr.start()

    assert state.display == ":77"
    assert mgr.status()["running"] is True
    assert mgr.browser_env()["DISPLAY"] == ":77"
    assert mgr.stop() is True
    assert mgr.stop() is False

    mgr._save_state(
        DesktopState(
            mode=DesktopMode.XEPHYR,
            display=":20",
            pid=99,
            workspace_index=None,
            started_at=1.0,
        )
    )
    monkeypatch.setattr(mgr, "is_display_alive", lambda display: True)
    monkeypatch.setattr(mgr, "_is_pid_alive", lambda pid: True)
    cfg.desktop.mode = DesktopMode.XEPHYR
    assert mgr._start_xephyr_mode(force=False).pid == 99


def test_desktop_workspace_and_xephyr_errors(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    from colonium.desktop.linux import LinuxDesktopManager

    cfg = default_config()
    cfg.data_dir = tmp_path
    cfg.desktop.mode = DesktopMode.WORKSPACE
    mgr = LinuxDesktopManager(cfg)

    monkeypatch.setattr("shutil.which", lambda name: None)
    with pytest.raises(RuntimeError, match="wmctrl"):
        mgr.start()

    cfg.desktop.mode = DesktopMode.XEPHYR
    with pytest.raises(RuntimeError, match="not found"):
        mgr.start()

    calls: list[list[str]] = []
    monkeypatch.setattr("shutil.which", lambda name: f"/usr/bin/{name}")
    monkeypatch.setattr("subprocess.run", lambda cmd, **kwargs: calls.append(cmd))
    cfg.desktop.mode = DesktopMode.WORKSPACE
    state = mgr.start()
    assert state.mode == DesktopMode.WORKSPACE
    assert calls[-1] == ["wmctrl", "-s", str(cfg.desktop.workspace_index)]


def test_wave_prepare_poll_settle_and_collect(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    from colonium import wave
    from colonium.sessions import SessionStore

    class Page:
        url = "https://chat.example/thread"

    class Adapter:
        service = ServiceName.CHATGPT
        start_url = "https://chat.example/"

        def __init__(self) -> None:
            self.opened: list[str] = []
            self.new_count = 0
            self.sent: list[str] = []

        def ensure_ready(self, page: Any) -> TaskStatus:
            return TaskStatus.DONE

        def open_thread(self, page: Any, url: str) -> None:
            self.opened.append(url)

        def new_chat(self, page: Any) -> None:
            self.new_count += 1

        def count_responses(self, page: Any) -> int:
            return 2

        def send(self, page: Any, prompt: str, files: list[Path] | None = None) -> None:
            self.sent.append(prompt)

        def poll_response_ready(self, *args: Any) -> tuple[bool, str, int]:
            return True, "answer", 2

        def extract_since(self, page: Any, before_count: int) -> tuple[str, str]:
            return "answer", "Model"

    store = SessionStore(db_path=tmp_path / "sessions.db")
    store.save_binding("s1", "alpha", ServiceName.CHATGPT, "https://chat.example/thread", 1)
    adapter = Adapter()
    slot = wave._WaveSlot(
        service=ServiceName.CHATGPT,
        adapter=cast(Any, adapter),
        page=cast(Any, Page()),
        browser_name="alpha",
        before_count=0,
    )

    prepared = wave._prepare_and_send(
        slot=slot,
        prompt="hello",
        files=[],
        fresh_chat=False,
        session_id="s1",
        store=store,
    )

    assert prepared.status == TaskStatus.TYPING
    assert prepared.before_count == 2
    assert adapter.opened == ["https://chat.example/thread"]

    monkeypatch.setattr(wave.time, "sleep", lambda seconds: None)
    wave._poll_until_ready([prepared], timeout_ms=10, stable_polls=1)
    assert prepared.status == TaskStatus.DONE

    slept: list[float] = []
    monkeypatch.setattr(wave.time, "time", lambda: 10.0)
    monkeypatch.setattr(wave.time, "sleep", slept.append)
    prepared.ready_at = 10.0
    wave._apply_settle([prepared], settle_ms=1000)
    assert slept == [1.0]

    monkeypatch.setattr(
        "colonium.runner._collect_response_artifacts",
        lambda *args, **kwargs: [
            ArtifactRecord(
                source="link",
                name="a.txt",
                path=str(tmp_path / "a.txt"),
                size_bytes=1,
            )
        ],
    )
    responses = wave._collect_slots(
        [prepared],
        store,
        "s1",
        "alpha",
        started=9.0,
        files=[Path("x.txt")],
        artifact_root=tmp_path,
    )

    assert responses[0].status == TaskStatus.DONE
    assert responses[0].attachments_sent == ["x.txt"]
    assert responses[0].artifacts_received[0].name == "a.txt"


def test_wave_collects_non_done_and_timeout(monkeypatch: pytest.MonkeyPatch) -> None:
    from colonium import wave
    from colonium.sessions import SessionStore

    class Page:
        url = "https://chat.example/thread"

    class EmptyAdapter:
        service = ServiceName.CLAUDE
        start_url = "https://claude.ai/new"

        def poll_response_ready(self, *args: Any) -> tuple[bool, str, int]:
            return False, "", 0

        def extract_since(self, page: Any, before_count: int) -> tuple[str, str]:
            return "", "Claude"

        def count_responses(self, page: Any) -> int:
            return 1

    slots = [
        wave._WaveSlot(
            ServiceName.CLAUDE, cast(Any, EmptyAdapter()), cast(Any, Page()), "alpha", 0
        ),
        wave._WaveSlot(
            ServiceName.GROK,
            cast(Any, EmptyAdapter()),
            cast(Any, Page()),
            "alpha",
            0,
            status=TaskStatus.AUTH_REQUIRED,
            error="login",
        ),
        wave._WaveSlot(
            ServiceName.PERPLEXITY,
            cast(Any, EmptyAdapter()),
            cast(Any, Page()),
            "alpha",
            0,
            status=TaskStatus.ERROR,
            error="boom",
        ),
    ]
    monkeypatch.setattr(wave.time, "sleep", lambda seconds: None)
    wave._poll_until_ready([slots[0]], timeout_ms=0, stable_polls=1)

    responses = wave._collect_slots(
        slots,
        SessionStore(),
        None,
        "alpha",
        started=0.0,
        files=[],
        artifact_root=None,
    )

    assert [response.status for response in responses] == [
        TaskStatus.TIMEOUT,
        TaskStatus.AUTH_REQUIRED,
        TaskStatus.ERROR,
    ]


def test_orchestrator_failover_and_non_wave_paths(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    from colonium.orchestrator import CouncilOrchestrator
    from colonium.sessions import SessionStore

    cfg = default_config()
    cfg.data_dir = tmp_path
    cfg.use_wave = False
    orch = CouncilOrchestrator(cfg)
    orch.sessions = SessionStore(db_path=tmp_path / "orch.db")

    class Launcher:
        def is_cdp_alive(self, port: int) -> bool:
            return True

    calls: list[str] = []

    def fake_run_single_task(**kwargs: Any) -> CouncilResponse:
        calls.append(kwargs["browser"].name)
        if len(calls) == 1:
            return CouncilResponse(
                browser=kwargs["browser"].name,
                service=kwargs["service"].value,
                status=TaskStatus.ERROR,
                error="HTTP 429 rate limit exceeded",
            )
        return CouncilResponse(
            browser=kwargs["browser"].name,
            service=kwargs["service"].value,
            status=TaskStatus.DONE,
            text="ok",
        )

    monkeypatch.setattr("colonium.runner.run_single_task", fake_run_single_task)
    response = orch._run_task_with_failover(
        cfg.browsers[0],
        ServiceName.CLAUDE,
        CouncilJobRequest(prompt="hi", session_id="s1", services=[ServiceName.CLAUDE]),
        1000,
        Launcher(),
        tmp_path,
    )

    assert response.status == TaskStatus.DONE
    assert calls == ["alpha", "zeta"]

    def raise_not_implemented(**kwargs: Any) -> CouncilResponse:
        raise NotImplementedError("not ready")

    monkeypatch.setattr("colonium.runner.run_single_task", raise_not_implemented)
    batch = orch._run_browser_wave(
        cfg.browsers[1],
        [ServiceName.GEMINI],
        CouncilJobRequest(prompt="hi", services=[ServiceName.GEMINI]),
        1000,
        Launcher(),
        tmp_path,
    )
    assert batch[0].status == TaskStatus.SKIPPED


def test_mcp_payloads_and_fake_server(monkeypatch: pytest.MonkeyPatch) -> None:
    from colonium import mcp_server

    class FakeOrchestrator:
        def run(self, request: CouncilJobRequest) -> Any:
            return types.SimpleNamespace(
                model_dump=lambda mode="json": {
                    "query": request.prompt,
                    "metadata": {"services": [service.value for service in request.services]},
                }
            )

    monkeypatch.setattr("colonium.orchestrator.CouncilOrchestrator", FakeOrchestrator)
    payload = mcp_server.run_ask_payload(prompt="hi", services=["claude"], browsers=["beta"])
    assert payload["metadata"]["services"] == ["claude"]

    class FakeFastMCP:
        def __init__(self, name: str) -> None:
            self.name = name
            self.resources: dict[str, Any] = {}
            self.tools: list[str] = []
            self.ran: str | None = None

        def resource(self, uri: str) -> Any:
            def decorator(func: Any) -> Any:
                self.resources[uri] = func
                return func

            return decorator

        def tool(self) -> Any:
            def decorator(func: Any) -> Any:
                self.tools.append(func.__name__)
                return func

            return decorator

        def run(self, transport: str) -> None:
            self.ran = transport

    mcp_module = types.ModuleType("mcp")
    server_module = types.ModuleType("mcp.server")
    fastmcp_module = types.ModuleType("mcp.server.fastmcp")
    fastmcp_module.FastMCP = FakeFastMCP  # type: ignore[attr-defined]
    server_module.fastmcp = fastmcp_module  # type: ignore[attr-defined]
    mcp_module.server = server_module  # type: ignore[attr-defined]
    monkeypatch.setitem(sys.modules, "mcp", mcp_module)
    monkeypatch.setitem(sys.modules, "mcp.server", server_module)
    monkeypatch.setitem(sys.modules, "mcp.server.fastmcp", fastmcp_module)

    server = cast(Any, mcp_server.create_mcp_server())

    assert server.name == "Colonium"
    assert "colonium://capabilities" in server.resources
    assert "colonium_ask" in server.tools


def test_model_apply_service_and_ui_helpers(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    from colonium import model_settings as ms

    cfg = default_config()
    cfg.data_dir = tmp_path

    seen_services: list[str] = []
    monkeypatch.setattr(
        ms,
        "_apply_service",
        lambda assignments, cfg, service: (
            seen_services.append(service)
            or [{"status": "applied", "assignment": assignments[0].to_dict()}]
        ),
    )
    for service in ["claude", "gemini", "grok", "perplexity"]:
        assert (
            ms.apply_models(service=service, browsers=["beta"], cfg=cfg)[0]["status"] == "applied"
        )
    assert seen_services == ["claude", "gemini", "grok", "perplexity"]

    unsupported = ms.ModelAssignment("beta", "chatgpt", "Custom", supported=False, note="nope")
    assert ms._apply_chatgpt_assignment(object(), unsupported) == ["nope"]
    profile = ms.ModelAssignment("epsilon", "chatgpt", "Profile instructions variant 1")
    assert ms._apply_chatgpt_assignment(object(), profile) == []
    other = ms.ModelAssignment("beta", "chatgpt", "Unknown")
    assert "not live-supported" in ms._apply_chatgpt_assignment(object(), other)[0]


class ModelPage:
    def __init__(self) -> None:
        self.locator_overrides: dict[str, LocatorSpy] = {}
        self.text_overrides: dict[str, LocatorSpy] = {}
        self.role_overrides: dict[tuple[str, str | None], LocatorSpy] = {}
        self.waits: list[int] = []

    def locator(self, selector: str) -> LocatorSpy:
        return self.locator_overrides.get(selector, LocatorSpy(text="Gemini 3.1 Pro"))

    def get_by_text(self, label: str, exact: bool = True) -> LocatorSpy:
        return self.text_overrides.get(label, LocatorSpy())

    def get_by_role(self, role: str, name: str | None = None) -> LocatorSpy:
        return self.role_overrides.get((role, name), LocatorSpy())

    def wait_for_timeout(self, ms: int) -> None:
        self.waits.append(ms)


def test_model_assignment_wrappers(monkeypatch: pytest.MonkeyPatch) -> None:
    from colonium import model_settings as ms

    calls: list[tuple[str, str]] = []
    monkeypatch.setattr(
        ms, "_select_claude_model", lambda page, label: calls.append(("model", label))
    )
    monkeypatch.setattr(
        ms, "_select_claude_effort", lambda page, effort: calls.append(("effort", effort))
    )
    monkeypatch.setattr(ms, "_set_claude_thinking", lambda page, enabled: "thinking unavailable")
    claude = ms.ModelAssignment("beta", "claude", "Sonnet", effort="High", thinking=True)
    assert ms._apply_claude_assignment(object(), claude) == ["thinking unavailable"]
    assert calls == [("model", "Sonnet"), ("effort", "High")]

    monkeypatch.setattr(ms, "_select_gemini_model", lambda page, label: f"missing {label}")
    monkeypatch.setattr(ms, "_select_gemini_thinking_level", lambda page, level: f"bad {level}")
    gemini = ms.ModelAssignment("beta", "gemini", "3.5 Flash", effort="Extended")
    assert ms._apply_gemini_assignment(object(), gemini) == ["missing 3.5 Flash", "bad Extended"]

    monkeypatch.setattr(ms, "_select_perplexity_model", lambda page, label: None)
    monkeypatch.setattr(ms, "_select_perplexity_search_mode", lambda page, level: "mode missing")
    perplexity = ms.ModelAssignment("beta", "perplexity", "Sonar", effort="Deep research")
    assert ms._apply_perplexity_assignment(object(), perplexity) == ["mode missing"]

    monkeypatch.setattr(ms, "_select_grok_model", lambda page, label: calls.append(("grok", label)))
    assert ms._apply_grok_assignment(object(), ms.ModelAssignment("beta", "grok", "Expert")) == []

    monkeypatch.setattr(ms, "_select_chatgpt_tool", lambda page, label: None)
    assert (
        ms._apply_chatgpt_assignment(object(), ms.ModelAssignment("beta", "chatgpt", "Web search"))
        == []
    )


def test_model_ui_helper_success_paths() -> None:
    from colonium import model_settings as ms

    page = ModelPage()
    page.locator_overrides["[data-testid='model-selector-dropdown']"] = LocatorSpy(attr="false")
    page.role_overrides[("switch", "Thinking")] = LocatorSpy(attr="false")

    ms._click_visible_text(cast(Any, page), "Sonnet", timeout=100)
    assert ms._click_optional_text(cast(Any, page), "More models") is True
    ms._open_claude_model_menu(cast(Any, page))
    ms._select_claude_model(cast(Any, page), "Sonnet")
    ms._select_claude_effort(cast(Any, page), "High")
    assert ms._set_claude_thinking(cast(Any, page), True) is None
    assert ms._select_gemini_model(cast(Any, page), "3.1 Pro") is None
    assert ms._select_gemini_thinking_level(cast(Any, page), "Extended") is None
    assert ms._gemini_current_model_matches(cast(Any, page), "3.1 Pro") is True
    ms._select_grok_model(cast(Any, page), "Expert")
    assert ms._select_perplexity_model(cast(Any, page), "Sonar") is None
    assert ms._select_perplexity_search_mode(cast(Any, page), "Deep research") is None
    assert ms._select_chatgpt_tool(cast(Any, page), "Web search") is None
    ms._open_chatgpt_tool_menu(cast(Any, page))


def test_model_ui_helper_failure_paths() -> None:
    from colonium import model_settings as ms

    class FilterFailLocator(LocatorSpy):
        def filter(self, has_text: str) -> LocatorSpy:
            return LocatorSpy(fail_wait=True)

    page = ModelPage()
    page.text_overrides["Missing"] = LocatorSpy(fail_wait=True)
    page.role_overrides[("switch", "Thinking")] = LocatorSpy(count=0)
    assert ms._click_optional_text(cast(Any, page), "Missing") is False
    assert "not visible" in (ms._set_claude_thinking(cast(Any, page), True) or "")

    fail_page = ModelPage()
    fail_page.locator_overrides["body"] = LocatorSpy(text="no matching heading")
    fail_page.locator_overrides["gem-menu-item, [role='menuitem']"] = FilterFailLocator()
    assert ms._select_gemini_model(cast(Any, fail_page), "3.5 Flash") == (
        "Gemini model option is not visible: 3.5 Flash"
    )
    assert ms._select_gemini_thinking_level(cast(Any, page), "Turbo") == (
        "Unsupported Gemini thinking level: Turbo"
    )

    no_menu = ModelPage()
    no_menu.locator_overrides["gem-menu-item, [role='menuitem']"] = LocatorSpy(
        count=0, fail_wait=True
    )
    no_menu.locator_overrides[
        "[data-test-id='bard-mode-menu-button'], [data-testid='bard-mode-menu-button']"
    ] = LocatorSpy(count=0)
    no_menu.locator_overrides["button[aria-label^='Open mode picker']"] = LocatorSpy(count=0)
    with pytest.raises(RuntimeError, match="Gemini model picker"):
        ms._open_gemini_model_menu(cast(Any, no_menu))
    assert "model menu is not visible" in (
        ms._select_gemini_thinking_level(cast(Any, no_menu), "Standard") or ""
    )
    no_menu.locator_overrides["body"] = LocatorSpy(fail_wait=True)
    assert ms._gemini_current_model_matches(cast(Any, no_menu), "3.1 Pro") is False

    click_fail = ModelPage()
    click_fail.locator_overrides["button[aria-label='Model']"] = LocatorSpy(fail_wait=True)
    click_fail.text_overrides["Missing"] = LocatorSpy(fail_wait=True)
    assert ms._select_perplexity_model(cast(Any, click_fail), "Missing") == (
        "Perplexity model option is not visible: Missing"
    )
    assert ms._select_perplexity_search_mode(cast(Any, page), "Unknown") == (
        "Unsupported Perplexity search mode: Unknown"
    )
    click_fail.locator_overrides["button[aria-label='Search']"] = LocatorSpy(fail_wait=True)
    assert ms._select_perplexity_search_mode(cast(Any, click_fail), "Search") is None
    click_fail.text_overrides["Deep research"] = LocatorSpy(fail_wait=True)
    assert ms._select_perplexity_search_mode(cast(Any, click_fail), "Deep research") == (
        "Perplexity search mode is not visible: Deep research"
    )
    assert ms._select_chatgpt_tool(cast(Any, click_fail), "Deep research") == (
        "ChatGPT composer tool is not visible: Deep research"
    )


def test_apply_service_handles_browser_outcomes(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    from colonium import model_settings as ms

    cfg = default_config()
    cfg.data_dir = tmp_path
    assignments = [
        ms.ModelAssignment("missing", "claude", "Sonnet 4.6"),
        ms.ModelAssignment("beta", "claude", "Sonnet 4.6"),
        ms.ModelAssignment("gamma", "claude", "Sonnet 4.6"),
    ]

    class Chromium:
        contexts = [object()]

    class PW:
        class ChromiumAPI:
            def connect_over_cdp(self, url: str, timeout: int) -> Chromium:
                if url.endswith(":9224"):
                    raise RuntimeError("cdp down")
                return Chromium()

        chromium = ChromiumAPI()

    class PlaywrightContext:
        def __enter__(self) -> PW:
            return PW()

        def __exit__(self, *args: Any) -> None:
            return None

    monkeypatch.setattr("playwright.sync_api.sync_playwright", lambda: PlaywrightContext())
    monkeypatch.setattr("colonium.runner._get_service_page", lambda ctx, adapter: object())
    monkeypatch.setattr(ms, "_apply_claude_assignment", lambda page, assignment: ["warn"])

    rows = ms._apply_service(assignments, cfg, "claude")

    assert [row["status"] for row in rows] == ["skipped", "partial", "error"]

    profile_rows = ms._apply_service([ms.CHATGPT_ASSIGNMENTS["epsilon"]], cfg, "chatgpt")
    assert profile_rows[0]["status"] == "applied"
    assert ms.model_plan(service="chatgpt", browsers=["beta"], cfg=cfg)[0]["service"] == "chatgpt"


def test_cli_commands_with_fakes(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    from colonium import cli

    cfg = default_config()
    cfg.data_dir = tmp_path
    monkeypatch.setattr(cli, "load_config", lambda: cfg)
    monkeypatch.setattr(cli, "save_config", lambda cfg: tmp_path / "config.json")

    assert cli.cmd_init(argparse.Namespace()) == 0

    class Desktop:
        def __init__(self, cfg: Any = None) -> None:
            self.cfg = cfg

        def start(self, force: bool = False) -> Any:
            return types.SimpleNamespace(mode=DesktopMode.XEPHYR)

        def status(self) -> dict[str, Any]:
            return {"view_hint": "hint"}

        def stop(self) -> bool:
            return True

        def load_state(self) -> bool:
            return True

    class Launcher:
        def launch_all(self, **kwargs: Any) -> list[Any]:
            browser = BrowserInstance(name="alpha", cdp_port=9222, profile_dir="p")
            return [types.SimpleNamespace(browser=browser, pid=1, cdp_url="http://127.0.0.1:9222")]

        def stop_all(self) -> int:
            return 1

        def health(self) -> list[dict[str, Any]]:
            return [{"name": "alpha"}]

    monkeypatch.setattr("colonium.desktop.linux.LinuxDesktopManager", Desktop)
    monkeypatch.setattr("colonium.browser.launcher.BrowserLauncher", Launcher)

    assert (
        cli.cmd_desktop_start(
            argparse.Namespace(mode="current", display=":1", workspace=None, force=False)
        )
        == 0
    )
    assert cli.cmd_desktop_stop(argparse.Namespace()) == 0
    assert cli.cmd_desktop_status(argparse.Namespace()) == 0
    assert (
        cli.cmd_browsers_launch(argparse.Namespace(name="alpha,beta", login=True, force=True)) == 0
    )
    assert cli.cmd_browsers_stop(argparse.Namespace()) == 0
    assert cli.cmd_browsers_health(argparse.Namespace()) == 0

    monkeypatch.setattr("colonium.capabilities.build_capabilities", lambda: {"service_order": []})
    assert cli.cmd_capabilities(argparse.Namespace(json=True)) == 0


def test_cli_ask_and_main_error_paths(monkeypatch: pytest.MonkeyPatch) -> None:
    from colonium import cli

    class FakeOrchestrator:
        def run(self, request: CouncilJobRequest) -> Any:
            return types.SimpleNamespace(
                summary=types.SimpleNamespace(failed=0, model_dump=lambda: {"failed": 0}),
                artifacts={"markdown": "m.md", "json": "r.json", "artifact_dir": "a"},
            )

    monkeypatch.setattr("colonium.orchestrator.CouncilOrchestrator", FakeOrchestrator)
    args = argparse.Namespace(
        service="claude,chatgpt",
        browser="alpha,beta",
        file=["input.txt"],
        prompt="hi",
        session_id="s",
        fresh_chat=True,
        all_browsers=True,
        timeout=100,
    )
    assert cli.cmd_ask(args) == 0

    parser = cli.build_parser()
    assert parser.parse_args(["ask", "-p", "hi"]).command == "ask"

    monkeypatch.setattr(
        cli, "build_parser", lambda: types.SimpleNamespace(parse_args=lambda argv: args)
    )
    args.func = lambda parsed: (_ for _ in ()).throw(RuntimeError("bad"))
    assert cli.main([]) == 1
