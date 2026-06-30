from __future__ import annotations

import argparse
import json
from typing import Any

from colonia.capabilities import build_capabilities
from colonia.config import load_config
from colonia.models import CouncilJobRequest, ServiceName


def health_payload() -> list[dict[str, Any]]:
    from colonia.browser.launcher import BrowserLauncher

    return BrowserLauncher().health()


def run_ask_payload(
    *,
    prompt: str,
    browsers: list[str] | None = None,
    services: list[str] | None = None,
    session_id: str | None = None,
    all_browsers: bool = False,
    timeout_ms: int = 180_000,
    fresh_chat: bool = False,
) -> dict[str, Any]:
    from colonia.orchestrator import CouncilOrchestrator

    selected_services = [
        ServiceName(service.strip()) for service in (services or [s.value for s in ServiceName])
    ]
    request = CouncilJobRequest(
        prompt=prompt,
        browsers=browsers or ["all"],
        services=selected_services,
        session_id=session_id,
        include_all_browsers=all_browsers,
        timeout_ms=timeout_ms,
        fresh_chat=fresh_chat,
    )
    result = CouncilOrchestrator().run(request)
    return result.model_dump(mode="json")


def model_plan_payload(
    *,
    service: str | None = None,
    browsers: list[str] | None = None,
) -> list[dict[str, Any]]:
    from colonia.model_settings import model_plan

    return model_plan(service=service, browsers=browsers)


def model_apply_payload(
    *,
    service: str = "claude",
    browsers: list[str] | None = None,
    dry_run: bool = True,
) -> list[dict[str, Any]]:
    from colonia.model_settings import apply_models

    return apply_models(service=service, browsers=browsers, dry_run=dry_run)


def create_mcp_server():
    try:
        from mcp.server.fastmcp import FastMCP
    except ModuleNotFoundError as exc:
        raise RuntimeError(
            "MCP support requires the Python MCP SDK. Install with: pip install 'mcp[cli]'"
        ) from exc

    mcp = FastMCP("Colonia")

    @mcp.resource("colonia://capabilities")
    def capabilities_resource() -> str:
        """Machine-readable Colonia capability matrix."""
        return json.dumps(build_capabilities(), indent=2)

    @mcp.resource("colonia://config")
    def config_resource() -> str:
        """Current Colonia config as JSON."""
        return load_config().model_dump_json(indent=2)

    @mcp.tool()
    def colonia_capabilities() -> dict[str, Any]:
        """Return Colonia service order, browser routing, model plans, presets, and caveats."""
        return build_capabilities()

    @mcp.tool()
    def colonia_health() -> list[dict[str, Any]]:
        """Return CDP/browser health for alpha-theta."""
        return health_payload()

    @mcp.tool()
    def colonia_ask(
        prompt: str,
        browsers: list[str] | None = None,
        services: list[str] | None = None,
        session_id: str | None = None,
        all_browsers: bool = False,
        timeout_ms: int = 180_000,
        fresh_chat: bool = False,
    ) -> dict[str, Any]:
        """Run a Colonia council query and return summary, responses, artifacts, and metadata."""
        return run_ask_payload(
            prompt=prompt,
            browsers=browsers,
            services=services,
            session_id=session_id,
            all_browsers=all_browsers,
            timeout_ms=timeout_ms,
            fresh_chat=fresh_chat,
        )

    @mcp.tool()
    def colonia_model_plan(
        service: str | None = None,
        browsers: list[str] | None = None,
    ) -> list[dict[str, Any]]:
        """Return planned model/profile assignments for chatbot accounts."""
        return model_plan_payload(service=service, browsers=browsers)

    @mcp.tool()
    def colonia_model_apply(
        service: str = "claude",
        browsers: list[str] | None = None,
        dry_run: bool = True,
    ) -> list[dict[str, Any]]:
        """Apply supported model/profile assignments. Dry-run defaults to true for safety."""
        return model_apply_payload(service=service, browsers=browsers, dry_run=dry_run)

    return mcp


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Run the Colonia MCP server")
    parser.add_argument(
        "--transport",
        choices=["stdio", "sse", "streamable-http"],
        default="stdio",
        help="MCP transport to use",
    )
    return parser


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    server = create_mcp_server()
    server.run(transport=args.transport)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
