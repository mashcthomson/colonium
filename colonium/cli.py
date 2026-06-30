#!/usr/bin/env python3
from __future__ import annotations

import argparse
import json
import sys

from colonium.config import load_config, save_config
from colonium.models import CouncilJobRequest, DesktopMode, ServiceName


def _print_json(data: object) -> None:
    print(json.dumps(data, indent=2, default=str))


def cmd_init(_: argparse.Namespace) -> int:
    cfg = load_config()
    cfg.data_dir.mkdir(parents=True, exist_ok=True)
    cfg.profiles_dir.mkdir(parents=True, exist_ok=True)
    cfg.runs_dir.mkdir(parents=True, exist_ok=True)
    cfg.state_dir.mkdir(parents=True, exist_ok=True)
    path = save_config(cfg)
    print(f"Initialized Colonium at {cfg.data_dir}")
    print(f"Config: {path}")
    print("Next:")
    print("  colonium desktop start")
    print("  colonium browsers launch --login   # Chrome profiles with chat sites")
    return 0


def cmd_desktop_start(args: argparse.Namespace) -> int:
    from colonium.desktop import create_desktop_manager

    cfg = load_config()
    if args.mode:
        cfg.desktop.mode = DesktopMode(args.mode)
    if args.display:
        cfg.desktop.display = args.display
    if args.workspace is not None:
        cfg.desktop.workspace_index = args.workspace
    mgr = create_desktop_manager(cfg)
    state = mgr.start(force=args.force)
    status = mgr.status()
    _print_json(status)
    print()
    print(status.get("view_hint", ""))
    if state.mode == DesktopMode.XEPHYR:
        print()
        print(
            "Tip: look for a window titled 'Colonium Desktop 2'. "
            "All council browsers will open inside it."
        )
    return 0


def cmd_desktop_stop(_: argparse.Namespace) -> int:
    from colonium.desktop import create_desktop_manager

    mgr = create_desktop_manager()
    stopped = mgr.stop()
    print("Colonium desktop stopped." if stopped else "No Colonium desktop was running.")
    return 0


def cmd_desktop_status(_: argparse.Namespace) -> int:
    from colonium.desktop import create_desktop_manager

    mgr = create_desktop_manager()
    _print_json(mgr.status())
    return 0


def cmd_browsers_launch(args: argparse.Namespace) -> int:
    from colonium.browser.launcher import BrowserLauncher
    from colonium.desktop import create_desktop_manager

    mgr = create_desktop_manager()
    if not mgr.load_state():
        print("Starting Colonium desktop first...")
        mgr.start()

    launcher = BrowserLauncher()
    names = args.name.split(",") if args.name else None
    launched = launcher.launch_all(
        names=names,
        login_urls=args.login,
        force=args.force,
    )
    _print_json(
        [{"name": lb.browser.name, "pid": lb.pid, "cdp_url": lb.cdp_url} for lb in launched]
    )
    if args.login:
        print()
        print("Log into each service in the opened Colonium browsers, then run council queries.")
    return 0


def cmd_browsers_stop(_: argparse.Namespace) -> int:
    from colonium.browser.launcher import BrowserLauncher

    n = BrowserLauncher().stop_all()
    print(f"Stopped {n} browser process group(s).")
    return 0


def cmd_browsers_health(_: argparse.Namespace) -> int:
    from colonium.browser.launcher import BrowserLauncher

    _print_json(BrowserLauncher().health())
    return 0


def cmd_capabilities(args: argparse.Namespace) -> int:
    from colonium.capabilities import build_capabilities

    data = build_capabilities()
    if args.json:
        _print_json(data)
        return 0
    print("Colonium capabilities")
    print(f"Service order: {', '.join(data['service_order'])}")
    print(f"Default browsers: {', '.join(data['browser_selection']['default_all'])}")
    print(
        "Reserve-inclusive browsers: "
        f"{', '.join(data['browser_selection']['reserve_inclusive_all'])}"
    )
    print(f"Skipped by default: {', '.join(data['browser_selection']['skipped_by_default'])}")
    print("Use --json for model plans, prompt presets, commands, and caveats.")
    return 0


def cmd_models_plan(args: argparse.Namespace) -> int:
    from colonium.model_settings import model_plan

    browsers = args.browser.split(",") if args.browser else None
    rows = model_plan(service=args.service, browsers=browsers)
    _print_json(rows)
    return 0


def cmd_models_apply(args: argparse.Namespace) -> int:
    from colonium.model_settings import apply_models

    browsers = args.browser.split(",") if args.browser else None
    rows = apply_models(
        service=args.service,
        browsers=browsers,
        dry_run=args.dry_run,
    )
    _print_json(rows)
    return 0 if all(row["status"] in {"applied", "planned"} for row in rows) else 1


def cmd_ask(args: argparse.Namespace) -> int:
    from colonium.orchestrator import CouncilOrchestrator

    services = [ServiceName(s.strip()) for s in args.service.split(",")]
    browsers = ["all"] if not args.browser else [b.strip() for b in args.browser.split(",")]
    files = [__import__("pathlib").Path(p) for p in (args.file or [])]

    req = CouncilJobRequest(
        prompt=args.prompt,
        session_id=args.session_id,
        files=files,
        browsers=browsers,
        services=services,
        fresh_chat=args.fresh_chat,
        include_all_browsers=args.all_browsers,
        timeout_ms=args.timeout,
    )
    progress_callback = _print_progress_event if getattr(args, "progress", False) else None
    orchestrator = CouncilOrchestrator()
    if progress_callback:
        result = orchestrator.run(req, progress_callback=progress_callback)
    else:
        result = orchestrator.run(req)
    _print_json(result.summary.model_dump())
    print()
    print(f"Report: {result.artifacts.get('markdown')}")
    print(f"JSON:   {result.artifacts.get('json')}")
    print(f"Artifacts: {result.artifacts.get('artifact_dir')}")
    return 0 if result.summary.failed == 0 else 1


def _print_progress_event(event: dict) -> None:
    finished = ", ".join(
        f"{item.get('browser')}/{item.get('service')}={item.get('status')}"
        for item in event.get("completed", [])
    )
    print(
        f"[colonium] finished {finished}; pending={event.get('pending_tasks', 0)}",
        file=sys.stderr,
    )


def build_parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(
        prog="colonium",
        description="Colonium — browser-based AI council for local agent workflows",
    )
    sub = p.add_subparsers(dest="command", required=True)

    init_p = sub.add_parser("init", help="Create ~/.colonium config and directories")
    init_p.set_defaults(func=cmd_init)

    desk = sub.add_parser("desktop", help="Manage the Colonium browser desktop")
    desk_sub = desk.add_subparsers(dest="desktop_cmd", required=True)

    ds = desk_sub.add_parser("start", help="Start or select the browser desktop")
    ds.add_argument(
        "--mode",
        choices=[m.value for m in DesktopMode],
        help="xephyr=Linux nested window, workspace=Linux wmctrl workspace, current=no isolation",
    )
    ds.add_argument("--display", help="Linux Xephyr display, default :20 from config")
    ds.add_argument("--workspace", type=int, help="Workspace index for workspace mode (0-based)")
    ds.add_argument("--force", action="store_true", help="Restart managed desktop if running")
    ds.set_defaults(func=cmd_desktop_start)

    dst = desk_sub.add_parser("stop", help="Stop the managed Colonium desktop")
    dst.set_defaults(func=cmd_desktop_stop)

    dsts = desk_sub.add_parser("status", help="Desktop status")
    dsts.set_defaults(func=cmd_desktop_status)

    br = sub.add_parser("browsers", help="Manage Chrome farm")
    br_sub = br.add_subparsers(dest="browsers_cmd", required=True)

    bl = br_sub.add_parser("launch", help="Launch Colonium Chrome profiles")
    bl.add_argument("--name", help="Comma-separated browser names (default: all 8)")
    bl.add_argument(
        "--login",
        action="store_true",
        help="Open all 5 chat sites in each browser for manual login",
    )
    bl.add_argument("--force", action="store_true", help="Relaunch even if CDP is up")
    bl.set_defaults(func=cmd_browsers_launch)

    bs = br_sub.add_parser("stop", help="Stop all Colonium Chrome processes")
    bs.set_defaults(func=cmd_browsers_stop)

    bh = br_sub.add_parser("health", help="CDP health per browser")
    bh.set_defaults(func=cmd_browsers_health)

    ask = sub.add_parser("ask", help="Run a council query")
    ask.add_argument("-p", "--prompt", required=True)
    ask.add_argument("--browser", help="Browser name(s), comma-separated")
    ask.add_argument(
        "--service",
        default="perplexity",
        help="Service(s), comma-separated (default: perplexity)",
    )
    ask.add_argument(
        "--session-id",
        help="Caller session ID — continue same chat threads across asks (7-day idle TTL)",
    )
    ask.add_argument("-f", "--file", action="append", help="Attachment path")
    ask.add_argument("--timeout", type=int, default=300_000)
    ask.add_argument(
        "--fresh-chat",
        action="store_true",
        help="Start new chat threads even when --session-id is set",
    )
    ask.add_argument(
        "--all-browsers",
        action="store_true",
        help="Use all non-skipped browsers, including reserve browsers",
    )
    ask.add_argument(
        "--progress",
        action="store_true",
        help="Print model completion progress to stderr while the council runs",
    )
    ask.set_defaults(func=cmd_ask)

    caps = sub.add_parser("capabilities", help="Describe Colonium as an AI-usable tool")
    caps.add_argument("--json", action="store_true", help="Print full capability JSON")
    caps.set_defaults(func=cmd_capabilities)

    models = sub.add_parser("models", help="Plan or apply chatbot model/profile settings")
    models_sub = models.add_subparsers(dest="models_cmd", required=True)

    mp = models_sub.add_parser("plan", help="Show planned model/profile assignments")
    mp.add_argument(
        "--service", choices=[s.value for s in ServiceName], help="Limit to one service"
    )
    mp.add_argument("--browser", help="Comma-separated browser names")
    mp.set_defaults(func=cmd_models_plan)

    ma = models_sub.add_parser("apply", help="Apply supported model/profile assignments")
    ma.add_argument(
        "--service",
        choices=[s.value for s in ServiceName],
        default="claude",
        help="Service to configure. Provider UIs change; use --dry-run before applying.",
    )
    ma.add_argument("--browser", help="Comma-separated browser names")
    ma.add_argument("--dry-run", action="store_true", help="Print planned changes without applying")
    ma.set_defaults(func=cmd_models_apply)

    return p


def main(argv: list[str] | None = None) -> int:
    parser = build_parser()
    args = parser.parse_args(argv)
    try:
        return args.func(args)
    except KeyboardInterrupt:
        print("\nInterrupted.", file=sys.stderr)
        return 130
    except Exception as e:
        print(f"Error: {e}", file=sys.stderr)
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
