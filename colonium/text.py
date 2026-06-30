from __future__ import annotations

import re
import unicodedata


CHATGPT_TRAILING_NOISE_PATTERNS = (
    re.compile(r"^upgrade to (plus|pro|team|chatgpt plus)\b", re.IGNORECASE),
    re.compile(r"^get smarter responses\b", re.IGNORECASE),
    re.compile(r"^try chatgpt plus\b", re.IGNORECASE),
    re.compile(r"^chatgpt can make mistakes\b", re.IGNORECASE),
    re.compile(r"^check important info\b", re.IGNORECASE),
    re.compile(r"^(copy|share|regenerate|thumbs up|thumbs down)$", re.IGNORECASE),
)


def normalize_response_markdown(text: str, *, service: str) -> str:
    cleaned = strip_provider_trailing_noise(text, service=service)
    return close_unclosed_code_fence(cleaned).strip()


def strip_provider_trailing_noise(text: str, *, service: str) -> str:
    lines = text.replace("\r\n", "\n").replace("\r", "\n").split("\n")
    while lines and not lines[-1].strip():
        lines.pop()

    patterns = CHATGPT_TRAILING_NOISE_PATTERNS if service == "chatgpt" else ()
    while lines and patterns:
        line = lines[-1].strip()
        if not line:
            lines.pop()
            continue
        if any(pattern.search(line) for pattern in patterns):
            lines.pop()
            continue
        break

    return "\n".join(lines)


def close_unclosed_code_fence(text: str) -> str:
    fence_count = sum(1 for line in text.splitlines() if line.strip().startswith("```"))
    if fence_count % 2 == 1:
        return text.rstrip() + "\n```"
    return text


def clean_model_label(label: str) -> str:
    cleaned = "".join(ch for ch in label if unicodedata.category(ch) not in {"Co", "Cc", "Cf"})
    return re.sub(r"\s+", " ", cleaned).strip()
