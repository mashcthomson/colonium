from __future__ import annotations


CHATGPT_PROMPT_PROFILES: dict[str, tuple[str, str]] = {
    "epsilon": (
        "operator",
        "Operator profile: be concise, execution-focused, and state the next action clearly.",
    ),
    "eta": (
        "research",
        "Research profile: separate verified facts from inference and call out uncertainty.",
    ),
    "theta": (
        "reviewer",
        "Reviewer profile: look for failure modes, missing tests, and weak assumptions first.",
    ),
}


def prompt_profile_name(*, browser: str, service: str) -> str:
    if service != "chatgpt":
        return ""
    profile = CHATGPT_PROMPT_PROFILES.get(browser)
    return profile[0] if profile else ""


def apply_prompt_profile(prompt: str, *, browser: str, service: str) -> str:
    if service != "chatgpt":
        return prompt
    profile = CHATGPT_PROMPT_PROFILES.get(browser)
    if not profile:
        return prompt
    _, instruction = profile
    return f"{instruction}\n\nUser request:\n{prompt}"
