from __future__ import annotations

import uuid
from concurrent.futures import ThreadPoolExecutor, as_completed
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Callable

from colonia.config import load_config
from colonia.consolidator import write_job_artifacts
from colonia.models import (
    BrowserInstance,
    ColoniaConfig,
    CouncilJobRequest,
    CouncilJobResult,
    CouncilJobSummary,
    CouncilResponse,
    ServiceName,
    TaskStatus,
    order_services,
)
from colonia.pools import BrowserPoolManager, is_rate_limit_error
from colonia.sessions import SessionStore


ProgressCallback = Callable[[dict[str, Any]], None]


class CouncilOrchestrator:
    def __init__(self, cfg: ColoniaConfig | None = None):
        self.cfg = cfg or load_config()
        self.pools = BrowserPoolManager(self.cfg)
        self.sessions = SessionStore()

    def _select_browsers(self, request: CouncilJobRequest) -> list:
        return self.pools.select_browsers(
            request.browsers,
            include_all_eight=request.include_all_browsers,
        )

    def _run_task_with_failover(
        self,
        browser,
        service,
        request: CouncilJobRequest,
        timeout_ms: int,
        launcher,
        artifact_root: Path,
    ) -> CouncilResponse:
        from colonia.runner import run_single_task

        if not launcher.is_cdp_alive(browser.cdp_port):
            return CouncilResponse(
                browser=browser.name,
                service=service.value,
                status=TaskStatus.SKIPPED,
                error=f"CDP not alive on port {browser.cdp_port}. Run: colonia browsers launch",
            )

        resp = run_single_task(
            browser=browser,
            service=service,
            prompt=request.prompt,
            files=request.files,
            fresh_chat=request.fresh_chat,
            session_id=request.session_id,
            timeout_ms=timeout_ms,
            session_store=self.sessions,
            artifact_root=artifact_root,
        )

        if (
            request.session_id
            and resp.status in (TaskStatus.ERROR, TaskStatus.TIMEOUT)
            and is_rate_limit_error(resp.error)
        ):
            reserve = self.pools.pick_reserve(request.session_id, browser.name, self.sessions)
            if reserve and launcher.is_cdp_alive(reserve.cdp_port):
                self.sessions.set_failover(request.session_id, browser.name, reserve.name)
                retry = run_single_task(
                    browser=reserve,
                    service=service,
                    prompt=request.prompt,
                    files=request.files,
                    fresh_chat=True,
                    session_id=request.session_id,
                    timeout_ms=timeout_ms,
                    session_store=self.sessions,
                    artifact_root=artifact_root,
                )
                retry.error = (
                    f"Failover from {browser.name} to {reserve.name}: {retry.error or ''}"
                ).strip(": ")
                return retry
        return resp

    def _run_browser_wave(
        self,
        browser: BrowserInstance,
        services: list[ServiceName],
        request: CouncilJobRequest,
        timeout_ms: int,
        launcher,
        artifact_root: Path,
    ) -> list[CouncilResponse]:
        from colonia.runner import run_single_task
        from colonia.wave import run_browser_wave

        if not launcher.is_cdp_alive(browser.cdp_port):
            return [
                CouncilResponse(
                    browser=browser.name,
                    service=s.value,
                    status=TaskStatus.SKIPPED,
                    error=f"CDP not alive on port {browser.cdp_port}. Run: colonia browsers launch",
                )
                for s in services
            ]

        if self.cfg.use_wave and len(services) > 1:
            responses = run_browser_wave(
                browser=browser,
                services=services,
                prompt=request.prompt,
                files=request.files,
                fresh_chat=request.fresh_chat,
                session_id=request.session_id,
                timeout_ms=timeout_ms,
                settle_ms=self.cfg.wave_settle_ms,
                session_store=self.sessions,
                artifact_root=artifact_root,
            )
        else:
            responses = []
            for service in services:
                try:
                    responses.append(
                        self._run_task_with_failover(
                            browser,
                            service,
                            request,
                            timeout_ms,
                            launcher,
                            artifact_root,
                        )
                    )
                except NotImplementedError as e:
                    responses.append(
                        CouncilResponse(
                            browser=browser.name,
                            service=service.value,
                            status=TaskStatus.SKIPPED,
                            error=str(e),
                        )
                    )
                except Exception as e:
                    responses.append(
                        CouncilResponse(
                            browser=browser.name,
                            service=service.value,
                            status=TaskStatus.ERROR,
                            error=str(e),
                        )
                    )
            return responses

        for i, resp in enumerate(responses):
            if (
                request.session_id
                and resp.status in (TaskStatus.ERROR, TaskStatus.TIMEOUT)
                and is_rate_limit_error(resp.error)
            ):
                service = services[i]
                reserve = self.pools.pick_reserve(request.session_id, browser.name, self.sessions)
                if reserve and launcher.is_cdp_alive(reserve.cdp_port):
                    self.sessions.set_failover(request.session_id, browser.name, reserve.name)
                    retry = run_single_task(
                        browser=reserve,
                        service=service,
                        prompt=request.prompt,
                        files=request.files,
                        fresh_chat=True,
                        session_id=request.session_id,
                        timeout_ms=timeout_ms,
                        session_store=self.sessions,
                        artifact_root=artifact_root,
                    )
                    retry.error = (
                        f"Failover from {browser.name} to {reserve.name}: {retry.error or ''}"
                    ).strip(": ")
                    responses[i] = retry

        return responses

    def run(
        self,
        request: CouncilJobRequest,
        progress_callback: ProgressCallback | None = None,
    ) -> CouncilJobResult:
        job_id = str(uuid.uuid4())
        started = datetime.now(timezone.utc).isoformat()
        browsers = self._select_browsers(request)
        services = order_services(list(request.services))
        timeout_ms = request.timeout_ms or self.cfg.default_timeout_ms
        artifact_root = self.cfg.runs_dir / job_id / "artifacts"

        turn_index = 0
        if request.session_id:
            turn_index = self.sessions.bump_turn(request.session_id)

        responses: list[CouncilResponse] = []
        summary = CouncilJobSummary(total_tasks=len(browsers) * len(services))
        progress_events: list[dict[str, Any]] = []

        from colonia.browser.launcher import BrowserLauncher

        launcher = BrowserLauncher(self.cfg)

        max_workers = min(len(browsers), self.cfg.max_concurrent_browsers) or 1
        with ThreadPoolExecutor(max_workers=max_workers) as pool:
            futures = {
                pool.submit(
                    self._run_browser_wave,
                    browser,
                    services,
                    request,
                    timeout_ms,
                    launcher,
                    artifact_root,
                ): browser
                for browser in browsers
            }
            for fut in as_completed(futures):
                try:
                    batch = fut.result()
                    responses.extend(batch)
                    for resp in batch:
                        if resp.status == TaskStatus.DONE:
                            summary.ok += 1
                        elif resp.status == TaskStatus.AUTH_REQUIRED:
                            summary.auth_required += 1
                        elif resp.status == TaskStatus.SKIPPED:
                            summary.skipped += 1
                        else:
                            summary.failed += 1
                    event = _progress_event(batch, summary.total_tasks - len(responses))
                    progress_events.append(event)
                    if progress_callback:
                        progress_callback(event)
                except Exception as e:
                    browser = futures[fut]
                    batch = []
                    for service in services:
                        batch.append(
                            CouncilResponse(
                                browser=browser.name,
                                service=service.value,
                                status=TaskStatus.ERROR,
                                error=str(e),
                            )
                        )
                    responses.extend(batch)
                    for _ in batch:
                        summary.failed += 1
                    event = _progress_event(batch, summary.total_tasks - len(responses))
                    progress_events.append(event)
                    if progress_callback:
                        progress_callback(event)

        completed = datetime.now(timezone.utc).isoformat()
        result = CouncilJobResult(
            job_id=job_id,
            query=request.prompt,
            started_at=started,
            completed_at=completed,
            summary=summary,
            responses=responses,
            metadata={
                "session_id": request.session_id,
                "turn_index": turn_index,
                "browsers": [b.name for b in browsers],
                "services": [s.value for s in services],
                "fresh_chat": request.fresh_chat,
                "use_wave": self.cfg.use_wave,
                "progress_events": progress_events,
            },
        )
        artifacts = write_job_artifacts(self.cfg, result)
        result.artifacts = artifacts
        return result


def _progress_event(batch: list[CouncilResponse], pending_tasks: int) -> dict[str, Any]:
    return {
        "completed": [
            {
                "browser": resp.browser,
                "service": resp.service,
                "status": resp.status.value,
                "model_label": resp.model_label,
                "text_preview": _text_preview(resp.text),
                "error": resp.error,
            }
            for resp in batch
        ],
        "pending_tasks": max(pending_tasks, 0),
    }


def _text_preview(text: str, limit: int = 240) -> str:
    compact = " ".join((text or "").split())
    return compact[:limit]
