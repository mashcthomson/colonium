from __future__ import annotations

from pathlib import Path

from scripts.check_repo_hygiene import iter_repo_files, scan_text


def test_hygiene_scan_allows_generic_documentation_examples() -> None:
    findings = scan_text(
        Path("README.md"),
        'data_dir = "/home/you/.colonium"\npath = "C:\\\\Users\\\\you\\\\exports"\n',
    )

    assert findings == []


def test_hygiene_scan_flags_machine_specific_paths() -> None:
    unix_home = "/home/" + "mash" + "/.colonium"
    windows_home = "C:" + "\\\\Users\\\\" + "claudebot" + "\\\\exports"
    findings = scan_text(
        Path("bad.txt"),
        f'data_dir = "{unix_home}"\npath = "{windows_home}"\n',
    )

    assert {finding.rule.code for finding in findings} == {"unix-home", "windows-home"}


def test_hygiene_scan_flags_personal_email_and_secret_tokens() -> None:
    email = "mash" + "@" + "gmail.com"
    gh_token = "ghp_" + ("1" * 36)
    openai_key = "sk-" + ("a" * 32)
    findings = scan_text(
        Path("bad.txt"),
        f"contact = mash@example.org\nalt = {email}\ntoken = {gh_token}\nopenai = {openai_key}\n",
    )

    assert {finding.rule.code for finding in findings} == {
        "personal-email",
        "github-token",
        "openai-key",
    }


def test_hygiene_scan_skips_generated_coverage_file(tmp_path: Path) -> None:
    coverage = tmp_path / ".coverage"
    coverage.write_text("/home/" + "mash" + "/private\n", encoding="utf-8")
    source = tmp_path / "source.py"
    source.write_text("print('ok')\n", encoding="utf-8")

    assert iter_repo_files(tmp_path) == [source]
