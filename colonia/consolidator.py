from __future__ import annotations

from colonia.models import ColoniaConfig, CouncilJobResult, CouncilResponse, TaskStatus
from colonia.text import normalize_response_markdown


def response_to_markdown_block(resp: CouncilResponse) -> list[str]:
    icon = {
        TaskStatus.DONE: "✅",
        TaskStatus.AUTH_REQUIRED: "🔒",
        TaskStatus.TIMEOUT: "⏱️",
        TaskStatus.ERROR: "❌",
        TaskStatus.SKIPPED: "⏭️",
    }.get(resp.status, "•")
    lines = [
        f"### {resp.browser} / {resp.service}"
        + (f" — {resp.model_label}" if resp.model_label else "")
        + f" {icon} ({resp.latency_ms / 1000:.1f}s)",
        "",
    ]
    if resp.error:
        lines.extend([f"**Error:** {resp.error}", ""])
    if resp.url:
        lines.extend([f"**URL:** {resp.url}", ""])
    if resp.artifacts_received:
        lines.extend(["**Artifacts:**", ""])
        for artifact in resp.artifacts_received:
            lines.append(f"- `{artifact.name}` -> `{artifact.path}`")
        lines.append("")
    if resp.text:
        lines.extend([normalize_response_markdown(resp.text, service=resp.service), ""])
    elif resp.status == TaskStatus.DONE:
        lines.extend(["*(empty response)*", ""])
    return lines


def job_to_markdown(result: CouncilJobResult) -> str:
    s = result.summary
    session_id = result.metadata.get("session_id")
    turn = result.metadata.get("turn_index")
    lines = [
        "# Colonia Council Report",
        "",
        f"**Job:** `{result.job_id}`",
    ]
    if session_id:
        lines.append(f"**Session:** `{session_id}` (turn {turn})")
    lines.extend(
        [
            f"**Query:** {result.query}",
            f"**Started:** {result.started_at}",
            f"**Completed:** {result.completed_at or '—'}",
            "",
            "## Summary",
            "",
            f"- Total tasks: {s.total_tasks}",
            f"- OK: {s.ok}",
            f"- Failed: {s.failed}",
            f"- Auth required: {s.auth_required}",
            f"- Skipped: {s.skipped}",
            "",
        ]
    )
    received_artifacts = [
        (resp, artifact) for resp in result.responses for artifact in resp.artifacts_received
    ]
    if received_artifacts:
        lines.extend(["## Artifacts", ""])
        for resp, artifact in received_artifacts:
            lines.append(
                f"- `{artifact.name}` from {resp.browser}/{resp.service} -> `{artifact.path}`"
            )
        lines.append("")
    lines.extend(
        [
            "## Responses",
            "",
        ]
    )
    for resp in result.responses:
        lines.extend(response_to_markdown_block(resp))
    return "\n".join(lines)


def write_job_artifacts(cfg: ColoniaConfig, result: CouncilJobResult) -> dict[str, str]:
    out_dir = cfg.runs_dir / result.job_id
    out_dir.mkdir(parents=True, exist_ok=True)
    json_path = out_dir / "result.json"
    md_path = out_dir / "report.md"
    artifact_dir = out_dir / "artifacts"
    artifact_dir.mkdir(parents=True, exist_ok=True)
    result.artifacts = {
        "json": str(json_path),
        "markdown": str(md_path),
        "artifact_dir": str(artifact_dir),
    }
    for response in result.responses:
        response.text = normalize_response_markdown(response.text, service=response.service)
    json_path.write_text(
        result.model_dump_json(indent=2),
        encoding="utf-8",
    )
    md_path.write_text(job_to_markdown(result), encoding="utf-8")
    return result.artifacts
