from __future__ import annotations

import re

_THINKING_PATTERNS: tuple[re.Pattern[str], ...] = (
    re.compile(r"^thinking\b", re.I),
    re.compile(r"thinking about", re.I),
    re.compile(r"^searching\b", re.I),
    re.compile(r"^generating\b", re.I),
    re.compile(r"^processing\b", re.I),
    re.compile(r"^one moment", re.I),
    re.compile(r"^please wait", re.I),
    re.compile(r"^working on", re.I),
    re.compile(r"^\.\.\.$"),
    re.compile(r"^…$"),
)


def is_thinking_placeholder(text: str) -> bool:
    """True when UI text is a transient status line, not a real assistant reply."""
    t = (text or "").strip()
    if len(t) < 4:
        return True
    lower = t.lower()
    for pattern in _THINKING_PATTERNS:
        if pattern.search(lower):
            return True
    if lower.startswith("thinking") and len(t) < 100:
        return True
    return False
