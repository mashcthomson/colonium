from __future__ import annotations

import json
import uuid
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any, cast

import pytest

from colonium.config import default_browsers, default_config, load_config, save_config
from colonium.consolidator import job_to_markdown, write_job_artifacts
from colonium.models import (
    ArtifactRecord,
    CouncilJobRequest,
    CouncilJobResult,
    CouncilJobSummary,
    CouncilResponse,
    ServiceName,
    TaskStatus,
)
from colonium.pools import (
    ACTIVE_POOL,
    RESERVE_POOL,
    SKIP_BY_DEFAULT,
    BrowserPoolManager,
    is_rate_limit_error,
)
from colonium.sessions import SESSION_IDLE_TTL, SessionStore


@pytest.fixture
def tmp_colonium(tmp_path, monkeypatch):
    data = tmp_path / "colonium"
    data.mkdir()
    cfg = default_config()
    cfg.data_dir = data
    save_config(cfg, data / "config.json")
    monkeypatch.setenv("COLONIUM_DATA_DIR", str(data))
    return data, cfg


@pytest.fixture
def session_db(tmp_path):
    return SessionStore(db_path=tmp_path / "test_sessions.db")


# 1
def test_default_browsers_eight_with_pools():
    browsers = default_browsers()
    assert len(browsers) == 8
    active = [b for b in browsers if b.pool == "active"]
    reserve = [b for b in browsers if b.pool == "reserve"]
    assert len(active) == 5
    assert len(reserve) == 3
    assert active[0].name == "alpha"
    assert reserve[0].name == "zeta"


# 2
def test_active_reserve_pool_constants():
    assert len(ACTIVE_POOL) == 5
    assert len(RESERVE_POOL) == 3
    assert ACTIVE_POOL.isdisjoint(RESERVE_POOL)
    assert SKIP_BY_DEFAULT == frozenset({"alpha"})


# 3
def test_session_store_save_and_get(session_db):
    session_db.save_binding("sess-1", "alpha", "claude", "https://claude.ai/chat/x", 2)
    b = session_db.get_binding("sess-1", "alpha", "claude")
    assert b is not None
    assert b.thread_url.endswith("/x")
    assert b.response_count == 2


# 4
def test_session_store_expired_binding_removed(session_db):
    old = datetime.now(timezone.utc) - SESSION_IDLE_TTL - timedelta(hours=1)
    with session_db._connect() as conn:
        conn.execute(
            """
            INSERT INTO thread_bindings
            (session_id, browser, service, thread_url, response_count, last_used_at)
            VALUES (?, ?, ?, ?, ?, ?)
            """,
            ("old", "alpha", "claude", "https://x", 1, old.isoformat()),
        )
    assert session_db.get_binding("old", "alpha", "claude") is None


# 5
def test_session_turn_counter(session_db):
    assert session_db.bump_turn("t1") == 1
    assert session_db.bump_turn("t1") == 2
    assert session_db.get_turn("t1") == 2


# 6
def test_session_failover_resolve(session_db):
    session_db.set_failover("s", "alpha", "zeta")
    assert session_db.resolve_browser("s", "alpha") == "zeta"
    assert session_db.resolve_browser("s", "beta") == "beta"


# 7
def test_session_clear(session_db):
    session_db.save_binding("s", "alpha", "claude", "https://a", 1)
    session_db.bump_turn("s")
    session_db.set_failover("s", "alpha", "zeta")
    session_db.clear_session("s")
    assert session_db.get_binding("s", "alpha", "claude") is None
    assert session_db.get_turn("s") == 0


# 8
def test_purge_expired(session_db):
    old = datetime.now(timezone.utc) - SESSION_IDLE_TTL - timedelta(days=1)
    with session_db._connect() as conn:
        conn.execute(
            """
            INSERT INTO thread_bindings
            (session_id, browser, service, thread_url, response_count, last_used_at)
            VALUES (?, ?, ?, ?, ?, ?)
            """,
            ("stale", "alpha", "grok", "https://g", 0, old.isoformat()),
        )
    n = session_db.purge_expired()
    assert n >= 1


# 9
def test_rate_limit_detection():
    assert is_rate_limit_error("HTTP 429 rate limit exceeded")
    assert is_rate_limit_error("Usage limit reached")
    assert not is_rate_limit_error("Login required")


# 10
def test_pool_select_active_only(tmp_colonium):
    _, cfg = tmp_colonium
    mgr = BrowserPoolManager(cfg)
    selected = mgr.select_browsers(["all"])
    assert len(selected) == 4
    assert all(b.pool == "active" for b in selected)
    assert [b.name for b in selected] == ["beta", "gamma", "delta", "epsilon"]


# 11
def test_pool_select_all_non_skipped_browsers(tmp_colonium):
    _, cfg = tmp_colonium
    mgr = BrowserPoolManager(cfg)
    selected = mgr.select_browsers(["all"], include_all_eight=True)
    assert len(selected) == 7
    assert [b.name for b in selected] == [
        "beta",
        "gamma",
        "delta",
        "epsilon",
        "zeta",
        "eta",
        "theta",
    ]


def test_pool_explicit_alpha_selection_still_works(tmp_colonium):
    _, cfg = tmp_colonium
    mgr = BrowserPoolManager(cfg)
    selected = mgr.select_browsers(["alpha"])
    assert [b.name for b in selected] == ["alpha"]


# 12
def test_pool_pick_reserve(tmp_colonium, session_db):
    _, cfg = tmp_colonium
    mgr = BrowserPoolManager(cfg)
    r = mgr.pick_reserve("s", "alpha", session_db)
    assert r is not None
    assert r.name == "zeta"
    session_db.set_failover("s", "beta", "zeta")
    r2 = mgr.pick_reserve("s", "alpha", session_db)
    assert r2 is not None
    assert r2.name == "eta"


# 13
def test_council_job_request_defaults():
    req = CouncilJobRequest(prompt="hi")
    assert req.session_id is None
    assert req.fresh_chat is False
    assert [s.value for s in req.services] == [
        "gemini",
        "claude",
        "grok",
        "perplexity",
        "chatgpt",
    ]


# 14
def test_consolidator_markdown_includes_session():
    result = CouncilJobResult(
        job_id="j1",
        query="test",
        started_at="2026-01-01T00:00:00Z",
        completed_at="2026-01-01T00:01:00Z",
        summary=CouncilJobSummary(total_tasks=1, ok=1),
        responses=[],
        metadata={"session_id": "claude-code-abc", "turn_index": 2},
    )
    md = job_to_markdown(result)
    assert "claude-code-abc" in md
    assert "turn 2" in md


# 15
def test_write_job_artifacts(tmp_colonium):
    data, cfg = tmp_colonium
    result = CouncilJobResult(
        job_id="artifact-test",
        query="q",
        started_at="now",
        completed_at="later",
        responses=[
            CouncilResponse(
                browser="alpha",
                service="perplexity",
                status=TaskStatus.DONE,
                text="answer",
            )
        ],
    )
    paths = write_job_artifacts(cfg, result)
    assert Path(paths["json"]).exists()
    assert Path(paths["markdown"]).exists()
    assert Path(paths["artifact_dir"]).is_dir()
    payload = json.loads(Path(paths["json"]).read_text())
    assert payload["responses"][0]["text"] == "answer"
    assert payload["artifacts"]["artifact_dir"].endswith("/runs/artifact-test/artifacts")


def test_consolidator_reports_received_artifacts(tmp_colonium):
    _, cfg = tmp_colonium
    result = CouncilJobResult(
        job_id="artifact-link-test",
        query="q",
        started_at="now",
        completed_at="later",
        responses=[
            CouncilResponse(
                browser="beta",
                service="chatgpt",
                status=TaskStatus.DONE,
                text="Generated the PDF.",
                artifacts_received=[
                    ArtifactRecord(
                        source="link",
                        name="answer.pdf",
                        path=str(cfg.runs_dir / "artifact-link-test" / "artifacts" / "answer.pdf"),
                        url="https://example.test/answer.pdf",
                        mime_type="application/pdf",
                        size_bytes=12,
                    )
                ],
            )
        ],
    )

    paths = write_job_artifacts(cfg, result)
    markdown = Path(paths["markdown"]).read_text()
    payload = json.loads(Path(paths["json"]).read_text())

    assert "## Artifacts" in markdown
    assert "answer.pdf" in markdown
    assert payload["responses"][0]["artifacts_received"][0]["name"] == "answer.pdf"


def test_collect_page_artifacts_downloads_file_links(tmp_path):
    from colonium.artifacts import collect_page_artifacts

    class FakeAPIResponse:
        ok = True
        headers = {
            "content-type": "application/pdf",
            "content-disposition": 'attachment; filename="report.pdf"',
        }

        def body(self):
            return b"%PDF-1.4"

    class FakeRequest:
        def get(self, url, timeout):
            assert url == "https://example.test/report.pdf"
            assert timeout == 30_000
            return FakeAPIResponse()

    class FakeContext:
        request = FakeRequest()

    class FakePage:
        url = "https://chat.example/thread"
        context = FakeContext()

        def evaluate(self, script):
            return [
                {
                    "href": "https://example.test/report.pdf",
                    "text": "Download report",
                    "download": "",
                },
                {
                    "href": "https://example.test/readme",
                    "text": "Not a file",
                    "download": "",
                },
            ]

    records = collect_page_artifacts(
        FakePage(),
        artifact_root=tmp_path,
        browser="beta",
        service="chatgpt",
    )

    assert len(records) == 1
    assert records[0].name == "report.pdf"
    assert Path(records[0].path).read_bytes() == b"%PDF-1.4"


# 16
def test_all_service_adapters_registered():
    from colonium.adapters import ADAPTERS, get_adapter

    for svc in ServiceName:
        assert svc in ADAPTERS
        adapter = get_adapter(svc)
        assert adapter.service == svc
        assert adapter.start_url.startswith("https://")


# 17
def test_config_roundtrip(tmp_path):
    cfg = default_config()
    cfg.data_dir = tmp_path
    p = save_config(cfg, tmp_path / "config.json")
    loaded = load_config(p)
    assert len(loaded.browsers) == 8
    assert loaded.browsers[0].cdp_port == 9222


# 18
def test_load_config_migrates_legacy_browser_pools(tmp_path):
    cfg = default_config()
    cfg.data_dir = tmp_path
    payload = cfg.model_dump(mode="json")
    for browser in payload["browsers"]:
        browser.pop("pool", None)
    p = tmp_path / "config.json"
    p.write_text(json.dumps(payload), encoding="utf-8")

    loaded = load_config(p)
    pools = {b.name: b.pool for b in loaded.browsers}
    assert pools["alpha"] == "active"
    assert pools["epsilon"] == "active"
    assert pools["zeta"] == "reserve"
    assert pools["theta"] == "reserve"


def test_browser_launcher_tiles_browser_windows(tmp_colonium):
    from colonium.browser.launcher import BrowserLauncher

    _, cfg = tmp_colonium
    launcher = BrowserLauncher(cfg)
    positions = []
    sizes = []

    for browser in cfg.browsers:
        cmd = launcher._chrome_cmd(browser, cfg.data_dir / browser.profile_dir)
        positions.append(next(arg for arg in cmd if arg.startswith("--window-position=")))
        sizes.append(next(arg for arg in cmd if arg.startswith("--window-size=")))

    assert len(set(positions)) == len(cfg.browsers)
    assert "--window-position=0,0" in positions
    assert all(size == "--window-size=480,540" for size in sizes)


def test_desktop_state_roundtrip_keeps_window_manager_pid(tmp_colonium):
    from colonium.desktop.linux import DesktopState, LinuxDesktopManager
    from colonium.models import DesktopMode

    _, cfg = tmp_colonium
    mgr = LinuxDesktopManager(cfg)
    mgr._save_state(
        DesktopState(
            mode=DesktopMode.XEPHYR,
            display=":20",
            pid=123,
            workspace_index=None,
            started_at=1.0,
            wm_pid=456,
        )
    )

    loaded = mgr.load_state()

    assert loaded is not None
    assert loaded.pid == 123
    assert loaded.wm_pid == 456


# 18
def test_orchestrator_skips_dead_cdp(tmp_colonium, monkeypatch):
    from colonium.orchestrator import CouncilOrchestrator

    _, cfg = tmp_colonium
    orch = CouncilOrchestrator(cfg)
    monkeypatch.setattr(
        "colonium.browser.launcher.BrowserLauncher.is_cdp_alive",
        lambda self, port: False,
    )
    req = CouncilJobRequest(
        prompt="hello",
        browsers=["alpha"],
        services=[ServiceName.PERPLEXITY],
    )
    result = orch.run(req)
    assert result.summary.skipped == 1
    assert result.summary.ok == 0


def test_orchestrator_normalizes_service_order(tmp_colonium, monkeypatch):
    from colonium.orchestrator import CouncilOrchestrator

    _, cfg = tmp_colonium
    orch = CouncilOrchestrator(cfg)
    monkeypatch.setattr(
        "colonium.browser.launcher.BrowserLauncher.is_cdp_alive",
        lambda self, port: False,
    )
    req = CouncilJobRequest(
        prompt="hello",
        browsers=["beta"],
        services=[
            ServiceName.CHATGPT,
            ServiceName.PERPLEXITY,
            ServiceName.GROK,
            ServiceName.CLAUDE,
            ServiceName.GEMINI,
        ],
    )

    result = orch.run(req)

    assert result.metadata["services"] == [
        "gemini",
        "claude",
        "grok",
        "perplexity",
        "chatgpt",
    ]


def test_capabilities_describe_tool_defaults(tmp_colonium):
    from colonium.capabilities import build_capabilities

    _, cfg = tmp_colonium
    data = build_capabilities(cfg)

    assert data["tool"] == "colonium"
    assert data["service_order"] == [
        "gemini",
        "claude",
        "grok",
        "perplexity",
        "chatgpt",
    ]
    assert data["browser_selection"]["skipped_by_default"] == ["alpha"]
    assert data["browser_selection"]["default_all"] == [
        "beta",
        "gamma",
        "delta",
        "epsilon",
    ]
    assert data["browser_selection"]["reserve_inclusive_all"] == [
        "beta",
        "gamma",
        "delta",
        "epsilon",
        "zeta",
        "eta",
        "theta",
    ]
    assert "reddit_scan" in data["prompt_skill_presets"]
    assert data["model_plan"]["chatgpt"]["desired_assignments"]["alpha"] == (
        "Deep research reserved/manual"
    )
    assert data["commands"]["models_apply_gemini"] == "colonium models apply --service gemini"
    assert data["commands"]["ask_progress"] == "colonium ask -p '<prompt>' --browser all --progress"
    assert "responses[].artifacts_received[]" in data["artifact_handling"]["result_fields"]
    assert "code-block-XX" in data["artifact_handling"]["code_block_artifacts"]
    assert "report.md" in data["artifact_handling"]["markdown_outputs"][0]
    assert (
        "#deep-research"
        in data["runtime_response_handling"]["chatgpt_tool_selection"]["explicit_tags"]
    )
    assert "ask --progress" in data["runtime_response_handling"]["progress_events"]
    assert "Haiku 4.5 extended" in data["model_plan"]["claude"]["verified_ui"]["not_found"]
    assert "Extended" in data["model_plan"]["gemini"]["verified_ui"]["thinking_labels"]
    assert "Web search" in data["model_plan"]["chatgpt"]["verified_ui"]["composer_tools"]


def test_mcp_health_payload_uses_browser_launcher(monkeypatch):
    from colonium import mcp_server

    expected = [{"name": "beta", "cdp_alive": True}]

    class FakeLauncher:
        def health(self):
            return expected

    monkeypatch.setattr("colonium.browser.launcher.BrowserLauncher", FakeLauncher)

    assert mcp_server.health_payload() == expected


def test_mcp_server_import_is_lazy_without_sdk():
    from colonium import mcp_server

    parser = mcp_server.build_parser()
    args = parser.parse_args([])
    assert args.transport == "stdio"


def test_mcp_model_payload_helpers(tmp_colonium):
    from colonium import mcp_server

    _, cfg = tmp_colonium
    rows = mcp_server.model_plan_payload(service="claude", browsers=["beta"])

    assert rows == [
        {
            "browser": "beta",
            "service": "claude",
            "model": "Sonnet 4.6",
            "effort": "Medium",
            "thinking": None,
            "supported": True,
            "note": "",
        }
    ]

    applied = mcp_server.model_apply_payload(
        service="claude",
        browsers=["beta"],
        dry_run=True,
    )

    assert applied[0]["status"] == "planned"
    assert cfg.data_dir.exists()


def test_model_plan_includes_claude_verified_assignments(tmp_colonium):
    from colonium.model_settings import model_plan

    _, cfg = tmp_colonium
    rows = model_plan(service="claude", cfg=cfg)
    by_browser = {row["browser"]: row for row in rows}

    assert by_browser["alpha"]["model"] == "Haiku 4.5"
    assert by_browser["beta"]["effort"] == "Medium"
    assert by_browser["delta"]["effort"] == "Max"
    assert by_browser["epsilon"]["thinking"] is True
    assert "extended" in by_browser["zeta"]["note"]


def test_model_plan_includes_gemini_verified_assignments(tmp_colonium):
    from colonium.model_settings import model_plan

    _, cfg = tmp_colonium
    rows = model_plan(service="gemini", cfg=cfg)
    by_browser = {row["browser"]: row for row in rows}

    assert by_browser["beta"]["model"] == "3.5 Flash"
    assert by_browser["gamma"]["model"] == "3.1 Flash-Lite"
    assert by_browser["delta"]["model"] == "3.1 Pro"
    assert by_browser["eta"]["effort"] == "Extended"


def test_model_apply_dry_run_for_claude(tmp_colonium):
    from colonium.model_settings import apply_models

    _, cfg = tmp_colonium
    rows = apply_models(service="claude", browsers=["beta", "epsilon"], dry_run=True, cfg=cfg)

    assert [row["status"] for row in rows] == ["planned", "planned"]
    assert rows[0]["assignment"]["effort"] == "Medium"
    assert rows[1]["assignment"]["thinking"] is True


def test_model_apply_reports_unsupported_for_unverified_services(tmp_colonium):
    from colonium.model_settings import apply_models

    _, cfg = tmp_colonium
    with pytest.raises(ValueError, match="Unknown service"):
        apply_models(service="unknown", browsers=["beta"], dry_run=False, cfg=cfg)


def test_chatgpt_model_apply_dry_run_marks_profile_lanes_runtime_supported(tmp_colonium):
    from colonium.model_settings import apply_models

    _, cfg = tmp_colonium
    rows = apply_models(
        service="chatgpt",
        browsers=["beta", "epsilon"],
        dry_run=True,
        cfg=cfg,
    )

    assert rows[0]["assignment"]["model"] == "Web search"
    assert rows[1]["assignment"]["supported"] is True
    assert "Runtime prompt profile" in rows[1]["assignment"]["note"]


def test_chatgpt_runtime_profile_apply_does_not_need_browser_cdp(tmp_colonium):
    from colonium.model_settings import apply_models

    _, cfg = tmp_colonium
    rows = apply_models(service="chatgpt", browsers=["epsilon", "eta", "theta"], cfg=cfg)

    assert [row["status"] for row in rows] == ["applied", "applied", "applied"]


def test_chatgpt_prompt_profiles_are_injected():
    from colonium.prompt_profiles import apply_prompt_profile, prompt_profile_name

    profiled = apply_prompt_profile("Summarize this.", browser="epsilon", service="chatgpt")

    assert prompt_profile_name(browser="epsilon", service="chatgpt") == "operator"
    assert "Operator profile" in profiled
    assert profiled.endswith("Summarize this.")
    assert apply_prompt_profile("Summarize this.", browser="beta", service="chatgpt") == (
        "Summarize this."
    )


def test_grok_and_perplexity_model_plans_are_per_browser(tmp_colonium):
    from colonium.model_settings import model_plan

    _, cfg = tmp_colonium
    grok = {row["browser"]: row for row in model_plan(service="grok", cfg=cfg)}
    perplexity = {row["browser"]: row for row in model_plan(service="perplexity", cfg=cfg)}

    assert grok["delta"]["model"] == "Expert"
    assert grok["epsilon"]["model"] == "Heavy"
    assert perplexity["delta"]["model"] == "Claude Sonnet 4.6"
    assert perplexity["epsilon"]["effort"] == "Deep research"


def test_model_browser_all_expands_and_unknown_rejected(tmp_colonium):
    from colonium.model_settings import apply_models, model_plan

    _, cfg = tmp_colonium
    planned = model_plan(service="claude", browsers=["all"], cfg=cfg)
    applied = apply_models(service="claude", browsers=["all"], dry_run=True, cfg=cfg)

    assert len(planned) == 8
    assert len(applied) == 8
    with pytest.raises(ValueError, match="Unknown browser"):
        model_plan(service="claude", browsers=["missing"], cfg=cfg)


def test_cli_models_apply_dry_run_parses():
    from colonium.cli import build_parser

    parser = build_parser()
    args = parser.parse_args(["models", "apply", "--service", "claude", "--dry-run"])

    assert args.models_cmd == "apply"
    assert args.service == "claude"
    assert args.dry_run is True


# 19
def test_desktop_manager_effective_display_current(tmp_colonium, monkeypatch):
    from colonium.desktop.linux import LinuxDesktopManager
    from colonium.models import DesktopMode

    _, cfg = tmp_colonium
    cfg.desktop.mode = DesktopMode.CURRENT
    monkeypatch.setenv("DISPLAY", ":99")
    mgr = LinuxDesktopManager(cfg)
    assert mgr.effective_display() == ":99"


# 20
def test_session_delete_binding(session_db):
    session_db.save_binding("s", "alpha", "gemini", "https://gemini.google.com/app", 3)
    session_db.delete_binding("s", "alpha", "gemini")
    assert session_db.get_binding("s", "alpha", "gemini") is None


# 21
def test_thinking_placeholder_detection():
    from colonium.placeholders import is_thinking_placeholder

    assert is_thinking_placeholder("Thinking about your request")
    assert is_thinking_placeholder("Searching...")
    assert is_thinking_placeholder("")
    assert not is_thinking_placeholder("COLONIUM_OK — the council is ready.")
    assert not is_thinking_placeholder("Here is a detailed answer about wave orchestration.")


# 22
def test_orchestrator_uses_wave_metadata(tmp_colonium, monkeypatch):
    from colonium.orchestrator import CouncilOrchestrator

    _, cfg = tmp_colonium
    cfg.use_wave = True
    orch = CouncilOrchestrator(cfg)
    monkeypatch.setattr(
        "colonium.browser.launcher.BrowserLauncher.is_cdp_alive",
        lambda self, port: False,
    )
    req = CouncilJobRequest(
        prompt="hello",
        browsers=["alpha"],
        services=[ServiceName.CHATGPT, ServiceName.CLAUDE],
    )
    result = orch.run(req)
    assert result.metadata["use_wave"] is True
    assert result.summary.skipped == 2


class FakeOverlayKeyboard:
    def __init__(self, page):
        self.page = page
        self.presses = []
        self.typed = ""

    def press(self, key):
        self.presses.append(key)

    def type(self, text, delay=0):
        self.typed = text


class FakeOverlayInput:
    def __init__(self, page):
        self.page = page
        self.clicked = False

    @property
    def first(self):
        return self

    def count(self):
        return 1

    def evaluate(self, script):
        if "tagName" in script:
            return "textarea"
        return not self.page.overlay_dismissed

    def is_visible(self, timeout=0):
        return self.page.overlay_dismissed

    def click(self, timeout=0):
        self.clicked = True

    def fill(self, text):
        self.page.filled = text

    def press(self, key):
        self.page.keyboard.press(key)


class FakeMissingButton:
    @property
    def first(self):
        return self

    @property
    def last(self):
        return self

    def count(self):
        return 0

    def is_visible(self, timeout=0):
        return False

    def is_enabled(self, timeout=0):
        return False

    def click(self, timeout=0, force=False):
        raise AssertionError("missing button should not be clicked")


class FakeOverlayPage:
    url = "https://chatgpt.com/"

    def __init__(self):
        self.overlay_dismissed = False
        self.keyboard = FakeOverlayKeyboard(self)
        self.waits = []
        self.filled = ""

    def evaluate(self, script, arg=None):
        if "COLONIUM_SAFE_DISMISS" in script:
            self.overlay_dismissed = True
            return 1
        raise AssertionError(f"unexpected page evaluate: {script[:80]}")

    def locator(self, selector):
        if "button" in selector:
            return FakeMissingButton()
        return FakeOverlayInput(self)

    def wait_for_timeout(self, ms):
        self.waits.append(ms)


def test_common_overlay_dismiss_makes_input_visible_before_ready():
    from colonium.adapters.dom import ChatGPTAdapter

    page = FakeOverlayPage()

    assert ChatGPTAdapter().ensure_ready(cast(Any, page)) == TaskStatus.DONE
    assert page.overlay_dismissed is True


def test_send_dismisses_overlay_before_finding_input():
    from colonium.adapters.dom import ChatGPTAdapter

    page = FakeOverlayPage()
    ChatGPTAdapter().send(cast(Any, page), "COLONIUM_OK")

    assert page.overlay_dismissed is True
    assert page.filled == "COLONIUM_OK"
    assert "Enter" in page.keyboard.presses


class FakePage:
    def __init__(self, url):
        self.url = url
        self.closed = False

    def close(self):
        self.closed = True


class FakeContext:
    def __init__(self, pages):
        self.pages = pages
        self.created = 0

    def new_page(self):
        self.created += 1
        page = FakePage("about:blank")
        self.pages.append(page)
        return page


def test_get_service_page_reuses_login_tab_instead_of_creating_new_tab():
    from colonium.adapters.dom import ChatGPTAdapter
    from colonium.runner import _get_service_page

    existing = FakePage("https://chatgpt.com/login")
    ctx = FakeContext([existing])

    page = _get_service_page(ctx, ChatGPTAdapter())

    assert page is existing
    assert ctx.created == 0


def test_get_service_page_keeps_one_tab_per_service_and_closes_duplicates():
    from colonium.adapters.dom import GeminiAdapter
    from colonium.runner import _get_service_page

    selected = FakePage("https://gemini.google.com/app/thread-a")
    duplicate = FakePage("https://gemini.google.com/app/thread-b")
    other_service = FakePage("https://claude.ai/chat/thread")
    ctx = FakeContext([duplicate, selected, other_service])

    page = _get_service_page(ctx, GeminiAdapter())

    assert page is duplicate
    assert selected.closed is True
    assert other_service.closed is False
    assert ctx.created == 0


def test_get_service_page_prefers_chat_thread_over_service_home():
    from colonium.adapters.grok import GrokAdapter
    from colonium.runner import _get_service_page

    home = FakePage("https://grok.com/")
    thread = FakePage("https://grok.com/c/thread-id")
    ctx = FakeContext([home, thread])

    page = _get_service_page(ctx, GrokAdapter())

    assert page is thread
    assert home.closed is True
    assert ctx.created == 0


def test_open_task_page_uses_fresh_tab_without_session():
    from colonium.adapters.dom import ClaudeAdapter
    from colonium.runner import _open_task_page

    existing = FakePage("https://claude.ai/chat/thread-id")
    ctx = FakeContext([existing])

    page = _open_task_page(ctx, ClaudeAdapter(), session_id=None, fresh_chat=False)

    assert page is not existing
    assert page.url == "about:blank"
    assert ctx.created == 1


def test_open_task_page_reuses_service_tab_for_session_continuation():
    from colonium.adapters.dom import ChatGPTAdapter
    from colonium.runner import _open_task_page

    existing = FakePage("https://chatgpt.com/c/thread-id")
    ctx = FakeContext([existing])

    page = _open_task_page(ctx, ChatGPTAdapter(), session_id="session-1", fresh_chat=False)

    assert page is existing
    assert ctx.created == 0


@pytest.mark.integration
def test_alpha_cdp_health_if_running():
    import urllib.error
    import urllib.request

    try:
        urllib.request.urlopen("http://127.0.0.1:9222/json/version", timeout=2)
        alive = True
    except (urllib.error.URLError, TimeoutError):
        alive = False
    if not alive:
        pytest.skip("alpha browser CDP not running")
    data = json.loads(
        urllib.request.urlopen("http://127.0.0.1:9222/json/version", timeout=2).read()
    )
    assert "Browser" in data


# Integration: live ask on alpha (optional, requires login)
@pytest.mark.integration
def test_live_ask_alpha_perplexity_session(tmp_colonium):
    import urllib.error
    import urllib.request

    try:
        urllib.request.urlopen("http://127.0.0.1:9222/json/version", timeout=2)
    except (urllib.error.URLError, TimeoutError):
        pytest.skip("alpha CDP not running")

    from colonium.orchestrator import CouncilOrchestrator

    _, cfg = tmp_colonium
    sid = f"test-{uuid.uuid4().hex[:8]}"
    orch = CouncilOrchestrator(cfg)
    req = CouncilJobRequest(
        prompt="Reply with exactly the word: COLONIUM_OK",
        session_id=sid,
        browsers=["alpha"],
        services=[ServiceName.PERPLEXITY],
        timeout_ms=120_000,
    )
    result = orch.run(req)
    assert result.metadata["session_id"] == sid
    assert result.metadata["turn_index"] == 1
    if result.summary.ok == 1:
        assert len(result.responses[0].text) > 0
        req2 = CouncilJobRequest(
            prompt="What was my previous question about? One short sentence.",
            session_id=sid,
            browsers=["alpha"],
            services=[ServiceName.PERPLEXITY],
            timeout_ms=120_000,
        )
        result2 = orch.run(req2)
        assert result2.metadata["turn_index"] == 2
    else:
        pytest.skip(
            f"perplexity not ready: {result.responses[0].error or result.responses[0].status}"
        )
