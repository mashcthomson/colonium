from __future__ import annotations

from typing import Any

from colonia.config import load_config
from colonia.models import DEFAULT_SERVICE_ORDER, ColoniaConfig
from colonia.pools import BrowserPoolManager, SKIP_BY_DEFAULT


PROMPT_SKILL_PRESETS: dict[str, dict[str, str]] = {
    "quick": {
        "label": "Quick answer",
        "prompt_hint": "Answer directly and keep latency/cost low.",
    },
    "quick_web_check": {
        "label": "Quick web check",
        "prompt_hint": "Check the current web and cite the most relevant sources briefly.",
    },
    "reddit_scan": {
        "label": "Reddit scan",
        "prompt_hint": "Check Reddit/community discussion and separate anecdotes from consensus.",
    },
    "citation_heavy": {
        "label": "Citation-heavy answer",
        "prompt_hint": "Prefer verifiable sources and include compact citations for key claims.",
    },
    "contrarian_review": {
        "label": "Contrarian review",
        "prompt_hint": "Look for counterarguments, failure modes, and what could make this wrong.",
    },
    "consensus": {
        "label": "Consensus synthesis",
        "prompt_hint": "Compare sources or viewpoints and identify the strongest shared conclusion.",
    },
    "reflection": {
        "label": "Reflective review",
        "prompt_hint": "Take a slower pass, check assumptions, and call out uncertainty.",
    },
}


DESIRED_MODEL_PLAN: dict[str, Any] = {
    "claude": {
        "order_note": "Claude runs after Gemini and before Grok.",
        "desired_assignments": {
            "alpha": "Haiku 4.5, light-model lane, reserved/manual",
            "beta": "Sonnet 4.6 medium",
            "gamma": "Sonnet 4.6 high",
            "delta": "Sonnet 4.6 max",
            "epsilon": "Sonnet 4.6 medium with thinking",
            "zeta": "Haiku 4.5 extended requested; fallback to Haiku 4.5 because extended was not visible",
            "eta": "Sonnet 4.6 high with thinking",
            "theta": "Sonnet 4.6 max with thinking",
        },
        "verified_ui": {
            "model_selector": "[data-testid='model-selector-dropdown']",
            "effort_trigger": "[data-testid='effort-menu-trigger']",
            "effort_options": ["Low", "Medium", "High", "Max"],
            "thinking_switch": (
                "role=switch[name='Thinking']; not visible in epsilon/eta/theta live menus"
            ),
            "available_models": ["Sonnet 4.6", "Haiku 4.5"],
            "upgrade_gated": ["Fable 5", "Opus 4.8", "Opus 4.7", "Opus 4.6", "Opus 3"],
            "not_found": ["Haiku 4.5 extended"],
        },
        "status": (
            "Claude model and effort controls verified; Haiku 4.5 extended and the "
            "epsilon/eta/theta Thinking switch were not visible in the live UI"
        ),
    },
    "gemini": {
        "order_note": "Gemini runs first to give slower pages time before ChatGPT.",
        "desired_assignments": {
            "alpha": "3.1 Pro standard, reserved/manual",
            "beta": "3.5 Flash standard",
            "gamma": "3.1 Flash-Lite extended thinking",
            "delta": "3.1 Pro standard",
            "epsilon": "3.1 Flash-Lite extended thinking",
            "zeta": "3.1 Pro extended thinking, reserved/manual",
            "eta": "3.5 Flash extended thinking",
            "theta": "3.1 Pro extended thinking",
        },
        "verified_ui": {
            "model_button": "[data-test-id='bard-mode-menu-button']",
            "available_models": ["3.1 Flash-Lite", "3.5 Flash", "3.1 Pro"],
            "thinking_labels": ["Thinking level", "Standard", "Extended"],
            "notable_browsers": {
                "all_checked": "Model menu exposes 3.1 Flash-Lite, 3.5 Flash, 3.1 Pro",
                "extended": "Thinking level submenu exposes Standard and Extended",
            },
        },
        "status": "Gemini model and Standard/Extended thinking controls verified",
    },
    "grok": {
        "order_note": "Grok runs after Claude.",
        "desired_assignments": {
            "alpha": "Fast, reserved/manual",
            "beta": "Fast",
            "gamma": "Auto",
            "delta": "Expert",
            "epsilon": "Heavy",
            "zeta": "Fast, reserved/manual",
            "eta": "Auto",
            "theta": "Expert",
        },
        "verified_ui": {
            "model_selector": "button[aria-label='Model select']",
            "model_options": ["Fast", "Auto", "Expert", "Heavy"],
            "other_menu_items": ["Unlock extended capabilities", "Custom Instructions"],
        },
        "model_switching": "Grok model menu verified",
        "recommended_presets": list(PROMPT_SKILL_PRESETS),
    },
    "perplexity": {
        "order_note": "Perplexity runs before ChatGPT.",
        "desired_assignments": {
            "alpha": "Sonar 2, reserved/manual",
            "beta": "Sonar 2 search",
            "gamma": "GPT-5.4 search",
            "delta": "Claude Sonnet 4.6 search",
            "epsilon": "Gemini 3.1 Pro deep research",
            "zeta": "GPT-5.5 Max model council, reserved/manual",
            "eta": "Kimi K2.6 learn step by step",
            "theta": "Nemotron 3 Ultra search",
        },
        "verified_ui": {
            "model_button": "button[aria-label='Model']",
            "search_button": "button[aria-label='Search']",
            "tool_button": "button[aria-label='Add files or tools']",
            "model_options": [
                "Sonar 2",
                "GPT-5.4",
                "GPT-5.5 Max",
                "Gemini 3.1 Pro",
                "Claude Sonnet 4.6",
                "Claude Opus 4.8 Max",
                "Kimi K2.6 New",
                "Nemotron 3 Ultra New",
            ],
            "search_options": [
                "Search",
                "Deep research",
                "Model council Max",
                "Learn step by step",
            ],
            "mode_tabs": ["Answer", "Links", "Images"],
            "source_indicators": ["source-count badges", "inline citation chips"],
        },
        "model_switching": "Perplexity model/search sheets verified",
        "recommended_presets": list(PROMPT_SKILL_PRESETS),
    },
    "chatgpt": {
        "order_note": "ChatGPT runs last so account state can settle after page load.",
        "desired_assignments": {
            "beta": "Web search enabled",
            "gamma": "Web search enabled",
            "delta": "Web search enabled",
            "epsilon": "Runtime operator prompt profile",
            "eta": "Runtime research prompt profile",
            "theta": "Runtime reviewer prompt profile",
            "alpha": "Deep research reserved/manual",
            "zeta": "Deep research reserved/manual",
        },
        "verified_ui": {
            "tier": "free accounts observed",
            "tool_button": "[data-testid='composer-plus-btn']",
            "composer_tools": ["Create image", "Thinking", "Deep research", "Web search"],
            "visible_model_labels": [
                "ChatGPT",
                "ChatGPT Plus",
                "Our smartest model & more",
                "ChatGPT Great for everyday tasks",
            ],
            "account_menu_labels": [
                "Upgrade plan",
                "Personalization",
                "Profile",
                "Settings",
                "Help",
                "Log out",
            ],
            "runtime_profiles": {
                "epsilon": "operator",
                "eta": "research",
                "theta": "reviewer",
            },
        },
        "status": (
            "ChatGPT composer tools verified for Web search and Deep research; "
            "profile variants are injected by Colonia at prompt time"
        ),
        "deep_research_note": "Deep research can take 10-30 minutes; use alpha/zeta only when explicitly needed.",
    },
}


def build_capabilities(cfg: ColoniaConfig | None = None) -> dict[str, Any]:
    cfg = cfg or load_config()
    pools = BrowserPoolManager(cfg)
    default_browsers = pools.select_browsers(["all"])
    reserve_inclusive = pools.select_browsers(["all"], include_all_eight=True)
    explicit_browsers = [browser.name for browser in cfg.browsers if browser.enabled]

    return {
        "tool": "colonia",
        "version": "0.1.0",
        "description": "Multi-browser AI council orchestrator for local logged-in chatbot sessions.",
        "service_order": [service.value for service in DEFAULT_SERVICE_ORDER],
        "browser_selection": {
            "skipped_by_default": sorted(SKIP_BY_DEFAULT),
            "default_all": [browser.name for browser in default_browsers],
            "reserve_inclusive_all": [browser.name for browser in reserve_inclusive],
            "explicit_allowed": explicit_browsers,
        },
        "model_plan": DESIRED_MODEL_PLAN,
        "prompt_skill_presets": PROMPT_SKILL_PRESETS,
        "artifact_handling": {
            "directory": "runs/<job_id>/artifacts/<browser>/<service>/",
            "result_fields": [
                "artifacts.artifact_dir",
                "responses[].artifacts_received[]",
            ],
            "markdown_outputs": [
                "runs/<job_id>/report.md",
                "runs/<job_id>/result.json",
            ],
            "code_block_artifacts": (
                "Fenced code blocks in provider replies are preserved in markdown and "
                "saved as separate code-block-XX files with language-based extensions."
            ),
            "downloaded_when": (
                "Provider response pages expose artifact links with file extensions or "
                "download attributes, such as PDF, CSV, DOCX, XLSX, ZIP, JSON, images, "
                "markdown, or text."
            ),
            "reply_cleanup": (
                "Provider upsell/footer noise is stripped before markdown/json output, "
                "and unclosed fenced code blocks are closed."
            ),
        },
        "runtime_response_handling": {
            "chatgpt_tool_selection": {
                "automatic": [
                    "Deep research for prompts asking for deep/thorough/comprehensive research",
                    "Web search for current/latest/today/as-of-now prompts",
                ],
                "explicit_tags": [
                    "#deep-research",
                    "#web-search",
                    "#chatgpt-tool:deep-research",
                    "#chatgpt-tool:web-search",
                    "#chatgpt-tool:none",
                    "#no-chatgpt-tool",
                ],
            },
            "progress_events": (
                "Council runs emit completed response batches with status/model previews "
                "and pending task counts; the CLI exposes this through ask --progress."
            ),
        },
        "commands": {
            "ask": (
                "colonia ask -p '<prompt>' --browser all --all-browsers "
                "--service gemini,claude,grok,perplexity,chatgpt --session-id <id>"
            ),
            "ask_progress": "colonia ask -p '<prompt>' --browser all --progress",
            "health": "colonia browsers health",
            "capabilities": "colonia capabilities --json",
            "models_plan": "colonia models plan --service gemini",
            "models_apply_dry_run": "colonia models apply --service gemini --dry-run",
            "models_apply_claude": "colonia models apply --service claude",
            "models_apply_gemini": "colonia models apply --service gemini",
            "models_apply_grok": "colonia models apply --service grok",
            "models_apply_perplexity": "colonia models apply --service perplexity",
            "models_apply_chatgpt": "colonia models apply --service chatgpt",
        },
        "caveats": [
            "Exact model labels are provider-UI dependent and should be verified before setting.",
            "ChatGPT runs last because account/session state may take a few seconds after reload.",
            "Alpha is skipped by default for now but remains explicitly selectable.",
            "Grok and Perplexity may need prompt-skill presets when model switching is unavailable.",
        ],
    }
