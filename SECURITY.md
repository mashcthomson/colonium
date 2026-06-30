# Security Policy

## Scope

Colonia is a local browser-automation tool. It does not require provider API keys for normal use, but it does handle:

- logged-in browser sessions
- prompts and model outputs
- local run artifacts
- optional MCP access from other local agents

That makes local data hygiene the primary security boundary.

## Reporting

If you find a security issue, do not open a public issue with exploit details.

Report it privately to the repository owner through GitHub security reporting if enabled, or through a private GitHub message/email channel already established with the maintainer.

## Safe Use

- Keep browser profiles under `~/.colonia/` private.
- Do not commit cookies, browser profiles, exports, run outputs, or local databases.
- Review `report.md`, `result.json`, and downloaded artifacts before sharing them.
- Use separate browser accounts/profiles for sensitive or high-risk prompts.
- Treat consumer model UIs as unstable automation targets; validate outputs before acting on them.

## Release Hygiene

Before publishing changes:

- run tests, lint, and type checks
- run `pip-audit`
- run `bandit -r colonia -x tests -ll`
- run `python scripts/check_repo_hygiene.py`
- confirm no local runtime directories or exported histories are staged

## Supported Versions

Security fixes are applied on the current main branch only.
