#!/usr/bin/env python3
"""Live integration tests on alpha browser — multiple session conditions."""

from __future__ import annotations

import json
import sys
import time
import uuid
from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path

from colonium.models import CouncilJobRequest, ServiceName, TaskStatus
from colonium.orchestrator import CouncilOrchestrator
from colonium.sessions import SessionStore


PROMPT_FIRST = "Reply with exactly one word: COLONIUM_OK (nothing else)."
PROMPT_FOLLOWUP = "In one short sentence: what single word did I ask you to reply with?"
TIMEOUT_MS = 180_000


@dataclass
class TestResult:
    name: str
    passed: bool
    detail: str
    latency_ms: int = 0


@dataclass
class TestRun:
    results: list[TestResult] = field(default_factory=list)

    def record(self, name: str, passed: bool, detail: str, latency_ms: int = 0) -> None:
        self.results.append(TestResult(name, passed, detail, latency_ms))
        mark = "PASS" if passed else "FAIL"
        print(f"  [{mark}] {name}: {detail[:120]}", flush=True)

    def summary(self) -> dict:
        passed = sum(1 for r in self.results if r.passed)
        return {
            "total": len(self.results),
            "passed": passed,
            "failed": len(self.results) - passed,
            "results": [
                {"name": r.name, "passed": r.passed, "detail": r.detail, "latency_ms": r.latency_ms}
                for r in self.results
            ],
        }


def _has_colonium_ok(text: str) -> bool:
    normalized = (text or "").lower().replace(" ", "").replace("-", "_")
    return "colonium_ok" in normalized


def _resp_text(result) -> str:
    if not result.responses:
        return ""
    return result.responses[0].text or ""


def _resp_status(result) -> tuple[TaskStatus, str | None]:
    if not result.responses:
        return TaskStatus.ERROR, "no response"
    r = result.responses[0]
    return r.status, r.error


def test_service_first_message(
    run: TestRun, orch: CouncilOrchestrator, service: ServiceName
) -> str | None:
    """Returns session_id used if success."""
    sid = f"live-{service.value}-{uuid.uuid4().hex[:6]}"
    t0 = time.time()
    result = orch.run(
        CouncilJobRequest(
            prompt=PROMPT_FIRST,
            session_id=sid,
            browsers=["alpha"],
            services=[service],
            timeout_ms=TIMEOUT_MS,
        )
    )
    ms = int((time.time() - t0) * 1000)
    status, err = _resp_status(result)
    text = _resp_text(result)
    ok = status == TaskStatus.DONE and _has_colonium_ok(text)
    run.record(
        f"1_new_session/{service.value}",
        ok,
        f"status={status.value} turn={result.metadata.get('turn_index')} "
        f"text_len={len(text)} err={err or ''} preview={text[:60]!r}",
        ms,
    )
    return sid if ok else None


def test_service_continue(
    run: TestRun, orch: CouncilOrchestrator, service: ServiceName, sid: str
) -> None:
    t0 = time.time()
    result = orch.run(
        CouncilJobRequest(
            prompt=PROMPT_FOLLOWUP,
            session_id=sid,
            browsers=["alpha"],
            services=[service],
            fresh_chat=False,
            timeout_ms=TIMEOUT_MS,
        )
    )
    ms = int((time.time() - t0) * 1000)
    status, err = _resp_status(result)
    text = _resp_text(result).lower()
    turn = result.metadata.get("turn_index", 0)
    # follow-up should be turn 2+ and ideally mention COLONIUM or OK
    ok = (
        status == TaskStatus.DONE
        and turn >= 2
        and len(text) > 0
        and ("colonium" in text or "ok" in text)
        and not text.strip().startswith("thinking")
    )
    run.record(
        f"2_continue_session/{service.value}",
        ok,
        f"status={status.value} turn={turn} text_preview={text[:80]!r} err={err or ''}",
        ms,
    )


def test_service_fresh_chat(
    run: TestRun, orch: CouncilOrchestrator, service: ServiceName, sid: str
) -> None:
    t0 = time.time()
    result = orch.run(
        CouncilJobRequest(
            prompt=PROMPT_FIRST,
            session_id=sid,
            browsers=["alpha"],
            services=[service],
            fresh_chat=True,
            timeout_ms=TIMEOUT_MS,
        )
    )
    ms = int((time.time() - t0) * 1000)
    status, err = _resp_status(result)
    text = _resp_text(result)
    ok = status == TaskStatus.DONE and _has_colonium_ok(text)
    run.record(
        f"3_fresh_chat/{service.value}",
        ok,
        f"status={status.value} fresh thread url={result.responses[0].url if result.responses else ''} "
        f"err={err or ''}",
        ms,
    )


def test_new_session_isolated(
    run: TestRun, orch: CouncilOrchestrator, service: ServiceName
) -> None:
    sid1 = f"iso-a-{uuid.uuid4().hex[:6]}"
    sid2 = f"iso-b-{uuid.uuid4().hex[:6]}"
    store = SessionStore()
    r1 = orch.run(
        CouncilJobRequest(
            prompt=PROMPT_FIRST,
            session_id=sid1,
            browsers=["alpha"],
            services=[service],
            timeout_ms=TIMEOUT_MS,
        )
    )
    url1 = (r1.responses[0].url or "") if r1.responses else ""
    r2 = orch.run(
        CouncilJobRequest(
            prompt=PROMPT_FIRST,
            session_id=sid2,
            browsers=["alpha"],
            services=[service],
            timeout_ms=TIMEOUT_MS,
        )
    )
    url2 = (r2.responses[0].url or "") if r2.responses else ""
    b1 = store.get_binding(sid1, "alpha", service)
    b2 = store.get_binding(sid2, "alpha", service)
    if not r1.responses or not r2.responses:
        ok = False
    else:
        ok = (
            r1.responses[0].status == TaskStatus.DONE
            and r2.responses[0].status == TaskStatus.DONE
            and url1 != url2
            and b1 is not None
            and b2 is not None
            and b1.thread_url != b2.thread_url
        )
    run.record(
        f"4_isolated_sessions/{service.value}",
        ok,
        f"url1={url1[:50]} url2={url2[:50]} same={url1 == url2}",
    )


def test_all_services_parallel_session(run: TestRun, orch: CouncilOrchestrator) -> str | None:
    sid = f"multi-{uuid.uuid4().hex[:6]}"
    t0 = time.time()
    result = orch.run(
        CouncilJobRequest(
            prompt=PROMPT_FIRST,
            session_id=sid,
            browsers=["alpha"],
            services=list(ServiceName),
            timeout_ms=TIMEOUT_MS,
        )
    )
    ms = int((time.time() - t0) * 1000)
    ok_count = result.summary.ok
    auth = result.summary.auth_required
    failed = result.summary.failed
    ok = ok_count == len(ServiceName) and all(
        _has_colonium_ok(r.text or "") for r in result.responses if r.status == TaskStatus.DONE
    )
    details = {r.service: r.status.value for r in result.responses}
    run.record(
        "5_all_five_services",
        ok,
        f"ok={ok_count} auth={auth} failed={failed} details={details}",
        ms,
    )
    return sid if ok_count >= 3 else None


def test_multi_service_turn3(run: TestRun, orch: CouncilOrchestrator, sid: str) -> None:
    """Follow-up turn 3 on shared multi-service session."""
    t0 = time.time()
    result = orch.run(
        CouncilJobRequest(
            prompt=PROMPT_FOLLOWUP,
            session_id=sid,
            browsers=["alpha"],
            services=list(ServiceName),
            fresh_chat=False,
            timeout_ms=TIMEOUT_MS,
        )
    )
    ms = int((time.time() - t0) * 1000)
    ok_count = sum(
        1 for r in result.responses if r.status == TaskStatus.DONE and len(r.text or "") > 0
    )
    turn_ok = sum(
        1
        for r in result.responses
        if r.status == TaskStatus.DONE and (result.metadata.get("turn_index") or 0) >= 2
    )
    details = {
        r.service: f"{r.status.value} turn={result.metadata.get('turn_index')} preview={(r.text or '')[:40]!r}"
        for r in result.responses
    }
    ok = ok_count >= 3 and turn_ok >= 3
    run.record(
        "6_multi_turn3_followup",
        ok,
        f"ok={ok_count} turn_ok={turn_ok} details={details}",
        ms,
    )


def main() -> int:
    print(f"Colonium live alpha tests — {datetime.now(timezone.utc).isoformat()}", flush=True)
    run = TestRun()
    orch = CouncilOrchestrator()

    services = list(ServiceName)
    successful_sessions: dict[ServiceName, str] = {}

    for svc in services:
        sid = test_service_first_message(run, orch, svc)
        if sid:
            successful_sessions[svc] = sid

    for svc, sid in successful_sessions.items():
        test_service_continue(run, orch, svc, sid)

    for svc, sid in list(successful_sessions.items())[:2]:  # fresh_chat on 2 services to save time
        test_service_fresh_chat(run, orch, svc, sid)

    for svc in list(successful_sessions.keys())[:2]:
        test_new_session_isolated(run, orch, svc)

    multi_sid = test_all_services_parallel_session(run, orch)
    if multi_sid:
        test_multi_service_turn3(run, orch, multi_sid)

    summary = run.summary()
    runs_dir = Path.home() / ".colonium" / "runs"
    runs_dir.mkdir(parents=True, exist_ok=True)
    out_path = runs_dir / f"live-test-{int(time.time())}.json"
    payload = {
        "timestamp": datetime.now(timezone.utc).isoformat(),
        "cdp": "http://127.0.0.1:9222",
        "browser": "alpha",
        **summary,
    }
    with open(out_path, "w", encoding="utf-8") as f:
        json.dump(payload, f, indent=2)

    print()
    print(f"=== {summary['passed']}/{summary['total']} passed ===")
    print(f"Report: {out_path}")
    return 0 if summary["failed"] == 0 else 1


if __name__ == "__main__":
    sys.exit(main())
