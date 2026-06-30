from __future__ import annotations

from dataclasses import asdict, dataclass
from typing import Any

from colonia.config import load_config
from colonia.models import BrowserInstance, ColoniaConfig


@dataclass(frozen=True)
class ModelAssignment:
    browser: str
    service: str
    model: str
    effort: str | None = None
    thinking: bool | None = None
    supported: bool = True
    note: str = ""

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


@dataclass(frozen=True)
class ModelApplyResult:
    browser: str
    service: str
    status: str
    assignment: dict[str, Any]
    error: str | None = None

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


CLAUDE_ASSIGNMENTS: dict[str, ModelAssignment] = {
    "alpha": ModelAssignment(
        browser="alpha",
        service="claude",
        model="Haiku 4.5",
        note="Light-model lane; alpha is skipped by default for council runs.",
    ),
    "beta": ModelAssignment(browser="beta", service="claude", model="Sonnet 4.6", effort="Medium"),
    "gamma": ModelAssignment(browser="gamma", service="claude", model="Sonnet 4.6", effort="High"),
    "delta": ModelAssignment(browser="delta", service="claude", model="Sonnet 4.6", effort="Max"),
    "epsilon": ModelAssignment(
        browser="epsilon",
        service="claude",
        model="Sonnet 4.6",
        effort="Medium",
        thinking=True,
    ),
    "zeta": ModelAssignment(
        browser="zeta",
        service="claude",
        model="Haiku 4.5",
        supported=True,
        note="Haiku 4.5 extended was requested but not visible in the verified Claude UI.",
    ),
    "eta": ModelAssignment(
        browser="eta",
        service="claude",
        model="Sonnet 4.6",
        effort="High",
        thinking=True,
    ),
    "theta": ModelAssignment(
        browser="theta",
        service="claude",
        model="Sonnet 4.6",
        effort="Max",
        thinking=True,
    ),
}


GEMINI_ASSIGNMENTS: dict[str, ModelAssignment] = {
    "alpha": ModelAssignment(
        "alpha",
        "gemini",
        "3.1 Pro",
        effort="Standard",
        note="Reserved/manual",
    ),
    "beta": ModelAssignment("beta", "gemini", "3.5 Flash", effort="Standard"),
    "gamma": ModelAssignment("gamma", "gemini", "3.1 Flash-Lite", effort="Extended"),
    "delta": ModelAssignment("delta", "gemini", "3.1 Pro", effort="Standard"),
    "epsilon": ModelAssignment("epsilon", "gemini", "3.1 Flash-Lite", effort="Extended"),
    "zeta": ModelAssignment("zeta", "gemini", "3.1 Pro", effort="Extended"),
    "eta": ModelAssignment("eta", "gemini", "3.5 Flash", effort="Extended"),
    "theta": ModelAssignment("theta", "gemini", "3.1 Pro", effort="Extended"),
}


GROK_ASSIGNMENTS: dict[str, ModelAssignment] = {
    "alpha": ModelAssignment("alpha", "grok", "Fast", note="Reserved/manual"),
    "beta": ModelAssignment("beta", "grok", "Fast"),
    "gamma": ModelAssignment("gamma", "grok", "Auto"),
    "delta": ModelAssignment("delta", "grok", "Expert"),
    "epsilon": ModelAssignment("epsilon", "grok", "Heavy"),
    "zeta": ModelAssignment("zeta", "grok", "Fast", note="Reserved/manual"),
    "eta": ModelAssignment("eta", "grok", "Auto"),
    "theta": ModelAssignment("theta", "grok", "Expert"),
}


PERPLEXITY_ASSIGNMENTS: dict[str, ModelAssignment] = {
    "alpha": ModelAssignment("alpha", "perplexity", "Sonar 2", note="Reserved/manual"),
    "beta": ModelAssignment("beta", "perplexity", "Sonar 2", effort="Search"),
    "gamma": ModelAssignment("gamma", "perplexity", "GPT-5.4", effort="Search"),
    "delta": ModelAssignment("delta", "perplexity", "Claude Sonnet 4.6", effort="Search"),
    "epsilon": ModelAssignment("epsilon", "perplexity", "Gemini 3.1 Pro", effort="Deep research"),
    "zeta": ModelAssignment("zeta", "perplexity", "GPT-5.5 Max", effort="Model council Max"),
    "eta": ModelAssignment("eta", "perplexity", "Kimi K2.6 New", effort="Learn step by step"),
    "theta": ModelAssignment("theta", "perplexity", "Nemotron 3 Ultra New", effort="Search"),
}


CHATGPT_ASSIGNMENTS: dict[str, ModelAssignment] = {
    "alpha": ModelAssignment("alpha", "chatgpt", "Deep research", note="Reserved/manual"),
    "beta": ModelAssignment("beta", "chatgpt", "Web search"),
    "gamma": ModelAssignment("gamma", "chatgpt", "Web search"),
    "delta": ModelAssignment("delta", "chatgpt", "Web search"),
    "epsilon": ModelAssignment(
        "epsilon",
        "chatgpt",
        "Profile instructions variant 1",
        note="Runtime prompt profile injected by Colonia.",
    ),
    "zeta": ModelAssignment("zeta", "chatgpt", "Deep research", note="Reserved/manual"),
    "eta": ModelAssignment(
        "eta",
        "chatgpt",
        "Profile instructions variant 2",
        note="Runtime prompt profile injected by Colonia.",
    ),
    "theta": ModelAssignment(
        "theta",
        "chatgpt",
        "Profile instructions variant 3",
        note="Runtime prompt profile injected by Colonia.",
    ),
}


def _enabled_browsers(cfg: ColoniaConfig) -> dict[str, BrowserInstance]:
    return {browser.name: browser for browser in cfg.browsers if browser.enabled}


def _resolve_browser_names(
    *,
    browsers: list[str] | None,
    cfg: ColoniaConfig,
) -> list[str]:
    enabled = _enabled_browsers(cfg)
    enabled_names = list(enabled)
    if not browsers:
        return enabled_names

    requested = [browser.strip() for browser in browsers if browser.strip()]
    unknown = set(requested).difference({*enabled, "all"})
    if unknown:
        raise ValueError(f"Unknown browser(s): {', '.join(sorted(unknown))}")

    if "all" in requested:
        return enabled_names
    return list(dict.fromkeys(requested))


def model_plan(
    *,
    service: str | None = None,
    browsers: list[str] | None = None,
    cfg: ColoniaConfig | None = None,
) -> list[dict[str, Any]]:
    cfg = cfg or load_config()
    wanted = set(_resolve_browser_names(browsers=browsers, cfg=cfg))
    services = [service] if service else ["claude", "gemini", "grok", "perplexity", "chatgpt"]
    assignments: list[ModelAssignment] = []

    for service_name in services:
        if service_name == "claude":
            assignments.extend(CLAUDE_ASSIGNMENTS.values())
        elif service_name == "gemini":
            assignments.extend(GEMINI_ASSIGNMENTS.values())
        elif service_name == "grok":
            assignments.extend(GROK_ASSIGNMENTS.values())
        elif service_name == "perplexity":
            assignments.extend(PERPLEXITY_ASSIGNMENTS.values())
        elif service_name == "chatgpt":
            assignments.extend(CHATGPT_ASSIGNMENTS.values())

    rows = [
        assignment.to_dict()
        for assignment in assignments
        if assignment.browser == "all" or assignment.browser in wanted
    ]
    return rows


def apply_models(
    *,
    service: str = "claude",
    browsers: list[str] | None = None,
    dry_run: bool = False,
    cfg: ColoniaConfig | None = None,
) -> list[dict[str, Any]]:
    if service not in {"claude", "gemini", "grok", "perplexity", "chatgpt"}:
        raise ValueError(f"Unknown service: {service}")

    cfg = cfg or load_config()
    selected_browsers = _resolve_browser_names(browsers=browsers, cfg=cfg)
    assignment_sets = {
        "claude": CLAUDE_ASSIGNMENTS,
        "gemini": GEMINI_ASSIGNMENTS,
        "grok": GROK_ASSIGNMENTS,
        "perplexity": PERPLEXITY_ASSIGNMENTS,
        "chatgpt": CHATGPT_ASSIGNMENTS,
    }
    assignments = [
        assignment_sets[service][name]
        for name in selected_browsers
        if name in assignment_sets[service]
    ]
    if dry_run:
        return [
            ModelApplyResult(
                browser=assignment.browser,
                service=assignment.service,
                status="planned",
                assignment=assignment.to_dict(),
            ).to_dict()
            for assignment in assignments
        ]

    if service == "claude":
        return _apply_service(assignments, cfg, "claude")
    if service == "gemini":
        return _apply_service(assignments, cfg, "gemini")
    if service == "grok":
        return _apply_service(assignments, cfg, "grok")
    if service == "perplexity":
        return _apply_service(assignments, cfg, "perplexity")
    return _apply_service(assignments, cfg, "chatgpt")


def _apply_service(
    assignments: list[ModelAssignment],
    cfg: ColoniaConfig,
    service: str,
) -> list[dict[str, Any]]:
    from playwright.sync_api import sync_playwright

    from colonia.adapters.dom import ChatGPTAdapter, ClaudeAdapter, GeminiAdapter
    from colonia.adapters.grok import GrokAdapter
    from colonia.adapters.perplexity import PerplexityAdapter
    from colonia.runner import _get_service_page

    enabled = _enabled_browsers(cfg)
    adapters = {
        "claude": ClaudeAdapter(),
        "gemini": GeminiAdapter(),
        "grok": GrokAdapter(),
        "perplexity": PerplexityAdapter(),
        "chatgpt": ChatGPTAdapter(),
    }
    handlers = {
        "claude": _apply_claude_assignment,
        "gemini": _apply_gemini_assignment,
        "grok": _apply_grok_assignment,
        "perplexity": _apply_perplexity_assignment,
        "chatgpt": _apply_chatgpt_assignment,
    }
    adapter = adapters[service]
    handler = handlers[service]
    results: list[dict[str, Any]] = []

    with sync_playwright() as pw:
        for assignment in assignments:
            browser = enabled.get(assignment.browser)
            if browser is None:
                results.append(
                    ModelApplyResult(
                        browser=assignment.browser,
                        service=assignment.service,
                        status="skipped",
                        assignment=assignment.to_dict(),
                        error="Browser is not enabled in config.",
                    ).to_dict()
                )
                continue
            if service == "chatgpt" and assignment.model.startswith("Profile instructions variant"):
                results.append(
                    ModelApplyResult(
                        browser=assignment.browser,
                        service=assignment.service,
                        status="applied",
                        assignment=assignment.to_dict(),
                    ).to_dict()
                )
                continue
            try:
                chromium = pw.chromium.connect_over_cdp(
                    f"http://127.0.0.1:{browser.cdp_port}",
                    timeout=30_000,
                )
                ctx = chromium.contexts[0] if chromium.contexts else chromium.new_context()
                page = _get_service_page(ctx, adapter)
                warnings = handler(page, assignment)
                results.append(
                    ModelApplyResult(
                        browser=assignment.browser,
                        service=assignment.service,
                        status="partial" if warnings else "applied",
                        assignment=assignment.to_dict(),
                        error="; ".join(warnings) if warnings else None,
                    ).to_dict()
                )
            except Exception as exc:
                results.append(
                    ModelApplyResult(
                        browser=assignment.browser,
                        service=assignment.service,
                        status="error",
                        assignment=assignment.to_dict(),
                        error=str(exc),
                    ).to_dict()
                )

    return results


def _apply_claude_assignment(page, assignment: ModelAssignment) -> list[str]:
    warnings: list[str] = []
    _select_claude_model(page, assignment.model)
    if assignment.effort:
        _select_claude_effort(page, assignment.effort)
    if assignment.thinking is not None:
        warning = _set_claude_thinking(page, assignment.thinking)
        if warning:
            warnings.append(warning)
    return warnings


def _apply_gemini_assignment(page, assignment: ModelAssignment) -> list[str]:
    warnings: list[str] = []
    warning = _select_gemini_model(page, assignment.model)
    if warning:
        warnings.append(warning)
    if assignment.effort:
        warning = _select_gemini_thinking_level(page, assignment.effort)
        if warning:
            warnings.append(warning)
    return warnings


def _apply_chatgpt_assignment(page, assignment: ModelAssignment) -> list[str]:
    if not assignment.supported:
        return [assignment.note or "This ChatGPT assignment is not live-supported yet."]
    if assignment.model in {"Web search", "Deep research"}:
        warning = _select_chatgpt_tool(page, assignment.model)
        return [warning] if warning else []
    if assignment.model.startswith("Profile instructions variant"):
        return []
    return [f"ChatGPT assignment is not live-supported: {assignment.model}"]


def _apply_grok_assignment(page, assignment: ModelAssignment) -> list[str]:
    _select_grok_model(page, assignment.model)
    return []


def _apply_perplexity_assignment(page, assignment: ModelAssignment) -> list[str]:
    warnings: list[str] = []
    warning = _select_perplexity_model(page, assignment.model)
    if warning:
        warnings.append(warning)
    if assignment.effort:
        warning = _select_perplexity_search_mode(page, assignment.effort)
        if warning:
            warnings.append(warning)
    return warnings


def _select_claude_model(page, label: str) -> None:
    _open_claude_model_menu(page)
    try:
        _click_visible_text(page, label, timeout=5_000)
    except Exception:
        _click_optional_text(page, "More models")
        _click_visible_text(page, label, timeout=10_000)
    page.wait_for_timeout(500)


def _select_claude_effort(page, effort: str) -> None:
    _open_claude_model_menu(page)
    page.locator("[data-testid='effort-menu-trigger']").click(timeout=10_000)
    page.locator(f"[data-testid='effort-option-{effort.lower()}']").click(timeout=10_000)
    page.wait_for_timeout(500)


def _set_claude_thinking(page, enabled: bool) -> str | None:
    _open_claude_model_menu(page)
    switch = page.get_by_role("switch", name="Thinking")
    if switch.count() == 0:
        return "Claude Thinking switch is not visible for this account/menu."
    checked = switch.get_attribute("aria-checked") == "true"
    if checked != enabled:
        switch.click(timeout=10_000)
        page.wait_for_timeout(500)
    return None


def _click_visible_text(page, label: str, *, timeout: int) -> None:
    option = page.get_by_text(label, exact=True).first
    option.wait_for(state="visible", timeout=timeout)
    option.click(timeout=timeout)


def _click_optional_text(page, label: str) -> bool:
    option = page.get_by_text(label, exact=True).first
    try:
        option.wait_for(state="visible", timeout=2_000)
        option.click(timeout=5_000)
        page.wait_for_timeout(250)
        return True
    except Exception:
        return False


def _open_claude_model_menu(page) -> None:
    dropdown = page.locator("[data-testid='model-selector-dropdown']")
    if dropdown.get_attribute("aria-expanded") == "true":
        return
    dropdown.click(timeout=10_000)
    page.wait_for_timeout(250)


def _select_gemini_model(page, label: str) -> str | None:
    try:
        _open_gemini_model_menu(page)
    except Exception:
        if _gemini_current_model_matches(page, label):
            return None
        raise
    item = page.locator("gem-menu-item, [role='menuitem']").filter(has_text=label).first
    try:
        item.wait_for(state="visible", timeout=5_000)
    except Exception:
        if _gemini_current_model_matches(page, label):
            return None
        return f"Gemini model option is not visible: {label}"
    item.click(timeout=10_000)
    page.wait_for_timeout(750)
    return None


def _select_gemini_thinking_level(page, level: str) -> str | None:
    if level not in {"Standard", "Extended"}:
        return f"Unsupported Gemini thinking level: {level}"
    try:
        _open_gemini_model_menu(page)
    except Exception as exc:
        return f"Gemini model menu is not visible: {exc}"
    thinking = page.locator("gem-menu-item[value='thinking_level']").first
    if thinking.count() == 0:
        thinking = (
            page.locator("gem-menu-item, [role='menuitem']").filter(has_text="Thinking level").first
        )
    try:
        thinking.wait_for(state="visible", timeout=3_000)
    except Exception:
        return "Gemini Thinking level control is not visible."
    thinking.click(timeout=10_000)
    page.wait_for_timeout(500)
    option = page.locator("gem-menu-item, [role='menuitem']").filter(has_text=level).last
    try:
        option.wait_for(state="visible", timeout=5_000)
    except Exception:
        return f"Gemini {level} thinking option is not visible."
    option.click(timeout=10_000, force=True)
    page.wait_for_timeout(500)
    return None


def _open_gemini_model_menu(page) -> None:
    menu_item = page.locator("gem-menu-item, [role='menuitem']").first
    try:
        menu_item.wait_for(state="visible", timeout=500)
        return
    except Exception:
        pass

    triggers = [
        page.locator(
            "[data-test-id='bard-mode-menu-button'], [data-testid='bard-mode-menu-button']"
        ).first,
        page.locator("button[aria-label^='Open mode picker']").first,
    ]
    last_error: Exception | None = None
    for trigger in triggers:
        if trigger.count() == 0:
            continue
        try:
            trigger.click(timeout=10_000, force=True)
            page.wait_for_timeout(500)
            menu_item.wait_for(state="visible", timeout=2_000)
            return
        except Exception as exc:
            last_error = exc
    if last_error:
        raise last_error
    raise RuntimeError("Gemini model picker trigger not found.")


def _gemini_current_model_matches(page, label: str) -> bool:
    try:
        heading = page.locator("body").inner_text(timeout=3_000).splitlines()[:3]
    except Exception:
        return False
    current = " ".join(heading).lower()
    aliases = {
        "3.1 pro": ["3.1 pro", "gemini pro", " pro"],
        "3.5 flash": ["3.5 flash"],
        "3.1 flash-lite": ["3.1 flash-lite", "flash-lite"],
    }
    return any(alias in current for alias in aliases.get(label.lower(), [label.lower()]))


def _select_grok_model(page, label: str) -> None:
    page.locator("button[aria-label='Model select']").click(timeout=10_000, force=True)
    page.wait_for_timeout(500)
    option = page.get_by_role("menuitem").filter(has_text=label).first
    option.wait_for(state="visible", timeout=10_000)
    option.click(timeout=10_000, force=True)
    page.wait_for_timeout(500)


def _select_perplexity_model(page, label: str) -> str | None:
    try:
        page.locator("button[aria-label='Model']").click(timeout=10_000, force=True)
        page.wait_for_timeout(500)
        _click_visible_text(page, label, timeout=5_000)
        page.wait_for_timeout(500)
        return None
    except Exception:
        return f"Perplexity model option is not visible: {label}"


def _select_perplexity_search_mode(page, label: str) -> str | None:
    if label not in {"Search", "Deep research", "Model council Max", "Learn step by step"}:
        return f"Unsupported Perplexity search mode: {label}"
    try:
        page.locator("button[aria-label='Search']").click(timeout=10_000, force=True)
        page.wait_for_timeout(500)
        _click_visible_text(page, label, timeout=5_000)
        page.wait_for_timeout(500)
        return None
    except Exception:
        if label == "Search":
            return None
        return f"Perplexity search mode is not visible: {label}"


def _select_chatgpt_tool(page, label: str) -> str | None:
    try:
        _open_chatgpt_tool_menu(page)
        option = page.get_by_text(label, exact=True).first
        option.wait_for(state="visible", timeout=10_000)
        option.click(timeout=10_000, force=True)
        page.wait_for_timeout(500)
        return None
    except Exception:
        return f"ChatGPT composer tool is not visible: {label}"


def _open_chatgpt_tool_menu(page) -> None:
    button = page.locator("[data-testid='composer-plus-btn']").first
    button.click(timeout=10_000, force=True)
    page.wait_for_timeout(500)
