#!/usr/bin/env python3
"""Fail if the repository contains obvious secrets or machine-specific private data."""

from __future__ import annotations

import re
from dataclasses import dataclass
from pathlib import Path


REPO_ROOT = Path(__file__).resolve().parent.parent

SKIP_DIRS = {
    ".git",
    ".venv",
    ".pytest_cache",
    ".ruff_cache",
    ".gstack",
    "__pycache__",
    ".colonium",
    "dist",
    "build",
    "htmlcov",
}

SKIP_NAMES = {
    ".coverage",
    "coverage.xml",
}

SKIP_SUFFIXES = {
    ".db",
    ".jpeg",
    ".jpg",
    ".pdf",
    ".png",
    ".pyc",
    ".sqlite",
    ".sqlite3",
    ".xml",
    ".webp",
    ".zip",
}


@dataclass(frozen=True)
class Rule:
    code: str
    pattern: re.Pattern[str]
    message: str


RULES = (
    Rule(
        code="private-key",
        pattern=re.compile(r"-----BEGIN [A-Z ]*PRIVATE KEY-----"),
        message="Private key material detected.",
    ),
    Rule(
        code="openai-key",
        pattern=re.compile(r"sk-[A-Za-z0-9_-]{20,}"),
        message="OpenAI-style secret detected.",
    ),
    Rule(
        code="github-token",
        pattern=re.compile(r"(?:ghp_[A-Za-z0-9]{20,}|github_pat_[A-Za-z0-9_]{20,})"),
        message="GitHub token detected.",
    ),
    Rule(
        code="aws-key",
        pattern=re.compile(r"AKIA[0-9A-Z]{16}"),
        message="AWS access key detected.",
    ),
    Rule(
        code="google-key",
        pattern=re.compile(r"AIza[0-9A-Za-z\\-_]{20,}"),
        message="Google API key detected.",
    ),
    Rule(
        code="personal-email",
        pattern=re.compile(
            r"[A-Za-z0-9._%+-]+@(?:gmail|outlook|proton|yahoo)\.[A-Za-z]{2,}",
            flags=re.IGNORECASE,
        ),
        message="Personal email address detected.",
    ),
    Rule(
        code="unix-home",
        pattern=re.compile(r"/home/(?!you/)[A-Za-z0-9._-]+/"),
        message="Machine-specific Unix home path detected.",
    ),
    Rule(
        code="windows-home",
        pattern=re.compile(
            r"[A-Za-z]:\\\\Users\\\\(?!you\\\\|username\\\\|USER\\\\)[^\\\\]+\\\\",
            flags=re.IGNORECASE,
        ),
        message="Machine-specific Windows home path detected.",
    ),
)


@dataclass(frozen=True)
class Finding:
    path: Path
    line_number: int
    rule: Rule
    line: str


def iter_repo_files(root: Path) -> list[Path]:
    files: list[Path] = []
    for path in root.rglob("*"):
        if not path.is_file():
            continue
        if any(part in SKIP_DIRS for part in path.parts):
            continue
        if path.name in SKIP_NAMES:
            continue
        if path.suffix.lower() in SKIP_SUFFIXES:
            continue
        files.append(path)
    return sorted(files)


def scan_text(path: Path, text: str) -> list[Finding]:
    findings: list[Finding] = []
    for line_number, line in enumerate(text.splitlines(), 1):
        for rule in RULES:
            if rule.pattern.search(line):
                findings.append(
                    Finding(
                        path=path,
                        line_number=line_number,
                        rule=rule,
                        line=line.strip(),
                    )
                )
    return findings


def scan_repo(root: Path) -> list[Finding]:
    findings: list[Finding] = []
    for path in iter_repo_files(root):
        try:
            text = path.read_text(encoding="utf-8")
        except FileNotFoundError:
            continue
        except UnicodeDecodeError:
            continue
        findings.extend(scan_text(path.relative_to(root), text))
    return findings


def main() -> int:
    findings = scan_repo(REPO_ROOT)
    if not findings:
        print("Repository hygiene check passed.")
        return 0

    print("Repository hygiene check failed:\n")
    for finding in findings:
        print(f"{finding.path}:{finding.line_number}: [{finding.rule.code}] {finding.rule.message}")
        print(f"  {finding.line}")
    return 1


if __name__ == "__main__":
    raise SystemExit(main())
