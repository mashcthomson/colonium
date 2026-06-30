# Security Policy

Colonium is a local browser-automation tool. It does not require model-provider
API keys for normal browser use, but it does operate around sensitive local
state:

- logged-in browser profiles
- cookies and session storage
- prompts and model responses
- downloaded artifacts
- local MCP access

Treat `~/.colonium/` as private data.

## Supported Versions

Security fixes are handled on the current `main` branch.

## Reporting A Vulnerability

Use GitHub private vulnerability reporting if it is available for this repository.

If private reporting is not available, open a public issue with only a high-level
summary. Do not include exploit details, secrets, cookies, browser profile data,
or private run artifacts in a public issue.

Useful reports include:

- affected commit or version
- operating system and Python version
- the command or workflow involved
- expected behavior
- observed behavior
- why the behavior could expose private data, credentials, or local access

## Local Data Boundaries

Colonium stores runtime state outside the repository by default:

```text
~/.colonium/config.json
~/.colonium/profiles/
~/.colonium/runs/
~/.colonium/state/
```

Do not commit these paths. They may contain cookies, browser history, prompts,
model replies, downloaded files, and run metadata.

## Safe Usage

- Use dedicated browser profiles or accounts for automation.
- Review generated `report.md`, `result.json`, and artifacts before sharing them.
- Do not run Colonium against prompts or files you would not want stored locally.
- Keep local MCP access limited to trusted agents and terminals. Do not expose it
  on an untrusted network.
- Use official provider APIs for production, high-volume, or policy-sensitive work.

## Release Checks

Before publishing changes, run:

```bash
python -m ruff check .
python -m pyright .
python -m pytest --cov=colonium --cov-report=term-missing --cov-fail-under=80 -q
python -m build
pip-audit --skip-editable
python -m bandit -r colonium scripts perplexity_export.py -x tests -ll
python scripts/check_repo_hygiene.py
```

The repository hygiene scan checks for common secret formats, personal email
addresses, and machine-specific home paths. It is not a replacement for human
review.
