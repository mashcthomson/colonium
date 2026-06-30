from __future__ import annotations

import argparse
import json
from pathlib import Path
from typing import Any, cast

from colonium.config import default_config
from colonium.models import (
    ArtifactRecord,
    BrowserInstance,
    CouncilJobRequest,
    CouncilJobResult,
    CouncilJobSummary,
    CouncilResponse,
    ServiceName,
    TaskStatus,
)


def test_chatgpt_ad_tail_is_removed_and_unclosed_code_fence_is_closed() -> None:
    from colonium.text import clean_model_label, normalize_response_markdown

    raw = """Here is the answer.

```python
print("ok")

Get smarter responses, upload files and images, and more.
Upgrade to Plus
"""

    cleaned = normalize_response_markdown(raw, service="chatgpt")

    assert "Upgrade to Plus" not in cleaned
    assert "Get smarter responses" not in cleaned
    assert cleaned.endswith("```")
    assert cleaned.count("```") == 2
    assert clean_model_label("Sonnet 4.6 Low\ue027") == "Sonnet 4.6 Low"


def test_common_adapter_extracts_markdown_code_blocks_from_dom() -> None:
    from colonium.adapters.base import ChatAdapter, DomSelectors

    class Adapter(ChatAdapter):
        service = ServiceName.CHATGPT
        start_url = "https://chatgpt.com/"
        selectors = DomSelectors(login_url_markers=(), assistant_selector=".assistant")

        def ensure_ready(self, page: Any) -> TaskStatus:
            return TaskStatus.DONE

    class Page:
        def evaluate(self, script: str, arg: Any = None) -> Any:
            assert "nodeToMarkdown" in script
            return ['Answer\n\n```python\nprint("ok")\n```', "GPT-5"]

    text, model = Adapter().extract_since(cast(Any, Page()), 0)

    assert model == "GPT-5"
    assert text == 'Answer\n\n```python\nprint("ok")\n```'


def test_fenced_code_blocks_are_saved_as_artifacts(tmp_path: Path) -> None:
    from colonium.artifacts import collect_code_artifacts

    text = """Use this:

```python
print("ok")
```

And this:

```json
{"ok": true}
```
"""

    records = collect_code_artifacts(
        text, artifact_root=tmp_path, browser="beta", service="chatgpt"
    )

    assert [record.source for record in records] == ["code_block", "code_block"]
    assert [record.name for record in records] == ["code-block-01.py", "code-block-02.json"]
    assert Path(records[0].path).read_text(encoding="utf-8") == 'print("ok")\n'
    assert Path(records[1].path).read_text(encoding="utf-8") == '{"ok": true}\n'


def test_runner_collects_link_and_code_artifacts(tmp_path: Path, monkeypatch) -> None:
    from colonium.runner import _collect_response_artifacts

    link_record = ArtifactRecord(
        source="link",
        name="answer.pdf",
        path=str(tmp_path / "answer.pdf"),
        size_bytes=1,
    )
    monkeypatch.setattr("colonium.artifacts.collect_page_artifacts", lambda **kwargs: [link_record])

    page = object()
    records = _collect_response_artifacts(
        page,
        artifact_root=tmp_path,
        browser="beta",
        service="chatgpt",
        text='```python\nprint("ok")\n```',
    )

    assert [record.source for record in records] == ["link", "code_block"]


def test_consolidator_writes_clean_markdown_and_code_artifact_links(tmp_path: Path) -> None:
    from colonium.consolidator import job_to_markdown, write_job_artifacts

    cfg = default_config()
    cfg.data_dir = tmp_path
    result = CouncilJobResult(
        job_id="clean-md",
        query="q",
        started_at="now",
        completed_at="later",
        summary=CouncilJobSummary(total_tasks=1, ok=1),
        responses=[
            CouncilResponse(
                browser="beta",
                service="chatgpt",
                status=TaskStatus.DONE,
                text='Answer\n```python\nprint("ok")\n```\nUpgrade to Plus',
                artifacts_received=[
                    ArtifactRecord(
                        source="code_block",
                        name="code-block-01.py",
                        path=str(tmp_path / "runs" / "clean-md" / "artifacts" / "code-block-01.py"),
                    )
                ],
            )
        ],
    )

    md = job_to_markdown(result)
    paths = write_job_artifacts(cfg, result)
    payload = json.loads(Path(paths["json"]).read_text(encoding="utf-8"))

    assert "Upgrade to Plus" not in md
    assert '```python\nprint("ok")\n```' in md
    assert "`code-block-01.py`" in md
    assert "Upgrade to Plus" not in Path(paths["markdown"]).read_text(encoding="utf-8")
    assert "Upgrade to Plus" not in payload["responses"][0]["text"]


def test_chatgpt_auto_selects_deep_research_and_web_search() -> None:
    from colonium.adapters.dom import ChatGPTAdapter, choose_chatgpt_tool

    assert choose_chatgpt_tool("Please do deep research on this market") == "Deep research"
    assert choose_chatgpt_tool("What is the latest news on this?") == "Web search"
    assert choose_chatgpt_tool("Summarize this local note") is None

    class Locator:
        def __init__(self) -> None:
            self.clicked = False

        @property
        def first(self) -> "Locator":
            return self

        def click(self, timeout: int = 0, force: bool = False) -> None:
            self.clicked = True

        def wait_for(self, state: str, timeout: int) -> None:
            return None

    class Page:
        def __init__(self) -> None:
            self.plus = Locator()
            self.deep = Locator()
            self.waits: list[int] = []

        def locator(self, selector: str) -> Locator:
            return self.plus

        def get_by_text(self, label: str, exact: bool = True) -> Locator:
            assert label == "Deep research"
            return self.deep

        def wait_for_timeout(self, ms: int) -> None:
            self.waits.append(ms)

    page = Page()
    ChatGPTAdapter().prepare_prompt(cast(Any, page), "run #deep-research on this")

    assert page.plus.clicked is True
    assert page.deep.clicked is True


def test_gemini_extractor_serializes_code_block_elements() -> None:
    from colonium.adapters.dom import _GEMINI_EXTRACT_JS

    assert "querySelectorAll('code-block')" in _GEMINI_EXTRACT_JS
    assert "```" in _GEMINI_EXTRACT_JS


def test_claude_extractor_strips_accessibility_heading_prefix() -> None:
    from colonium.adapters.dom import ClaudeAdapter

    class Page:
        def evaluate(self, script: str, arg: Any = None) -> Any:
            assert "Claude responded:" in script
            return ["COLONIUM_OK", "Sonnet 4.6 Low"]

    text, model = ClaudeAdapter().extract_since(cast(Any, Page()), 0)

    assert text == "COLONIUM_OK"
    assert model == "Sonnet 4.6 Low"


def test_orchestrator_records_progress_events(tmp_path: Path, monkeypatch) -> None:
    from colonium.orchestrator import CouncilOrchestrator

    cfg = default_config()
    cfg.data_dir = tmp_path
    cfg.use_wave = False
    orch = CouncilOrchestrator(cfg)
    events: list[dict[str, Any]] = []

    def fake_run_browser_wave(
        browser: BrowserInstance,
        services: list[ServiceName],
        request: CouncilJobRequest,
        timeout_ms: int,
        launcher: Any,
        artifact_root: Path,
    ) -> list[CouncilResponse]:
        return [
            CouncilResponse(
                browser=browser.name,
                service=services[0].value,
                model_label="Model",
                status=TaskStatus.DONE,
                text=f"{browser.name} answer",
            )
        ]

    monkeypatch.setattr(orch, "_run_browser_wave", fake_run_browser_wave)

    result = orch.run(
        CouncilJobRequest(prompt="hi", browsers=["beta", "gamma"], services=[ServiceName.CHATGPT]),
        progress_callback=events.append,
    )

    assert result.summary.ok == 2
    assert len(events) == 2
    assert events[0]["pending_tasks"] == 1
    assert events[0]["completed"][0]["text_preview"] == "beta answer"
    assert result.metadata["progress_events"] == events


def test_cli_progress_flag_prints_updates(monkeypatch, capsys) -> None:
    from colonium import cli

    class FakeOrchestrator:
        def run(self, request: CouncilJobRequest, progress_callback: Any = None) -> Any:
            if progress_callback:
                progress_callback(
                    {
                        "completed": [{"browser": "beta", "service": "chatgpt", "status": "done"}],
                        "pending_tasks": 1,
                    }
                )
            return type(
                "Result",
                (),
                {
                    "summary": type("Summary", (), {"failed": 0, "model_dump": lambda self: {}})(),
                    "artifacts": {
                        "markdown": "m.md",
                        "json": "r.json",
                        "artifact_dir": "artifacts",
                    },
                },
            )()

    monkeypatch.setattr("colonium.orchestrator.CouncilOrchestrator", FakeOrchestrator)

    assert (
        cli.cmd_ask(
            argparse.Namespace(
                service="chatgpt",
                browser="beta",
                file=[],
                prompt="hi",
                session_id=None,
                fresh_chat=False,
                all_browsers=False,
                timeout=100,
                progress=True,
            )
        )
        == 0
    )

    captured = capsys.readouterr()
    assert "finished beta/chatgpt=done" in captured.err
    assert "pending=1" in captured.err
