from __future__ import annotations

from pathlib import Path

from scripts.check_repo_hygiene import scan_text


def test_hygiene_scan_allows_generic_documentation_examples() -> None:
    findings = scan_text(
        Path("README.md"),
        'data_dir = "/home/you/.colonia"\n'
        'path = "C:\\\\Users\\\\you\\\\exports"\n',
    )

    assert findings == []


def test_hygiene_scan_flags_machine_specific_paths() -> None:
    unix_home = "/home/" + "mash" + "/.colonia"
    windows_home = "C:" + "\\\\Users\\\\" + "claudebot" + "\\\\exports"
    findings = scan_text(
        Path("bad.txt"),
        f'data_dir = "{unix_home}"\n'
        f'path = "{windows_home}"\n',
    )

    assert {finding.rule.code for finding in findings} == {"unix-home", "windows-home"}


def test_hygiene_scan_flags_personal_email_and_secret_tokens() -> None:
    email = "mash" + "@" + "gmail.com"
    gh_token = "ghp_" + ("1" * 36)
    openai_key = "sk-" + ("a" * 32)
    findings = scan_text(
        Path("bad.txt"),
        "contact = mash@example.org\n"
        f"alt = {email}\n"
        f"token = {gh_token}\n"
        f"openai = {openai_key}\n",
    )

    assert {finding.rule.code for finding in findings} == {
        "personal-email",
        "github-token",
        "openai-key",
    }
