# Colonia

**A non-API LLM council for research and consulting workflows in your AI agent.**

GitHub repository: `mashcthomson/colonium`  
Package and CLI name: `colonia`

Colonia drives your own logged-in browser sessions instead of calling model APIs. It can ask the same prompt across ChatGPT, Claude, Gemini, Grok, and Perplexity, then save a clean markdown report, structured JSON, progress metadata, and any linked or code-block artifacts the models produce.

It is built for local agent workflows where you want multiple consumer LLM products to act like a council without moving secrets into provider APIs.

## Public Repo Guarantees

This repository is intended to stay clean of:

- API keys, tokens, and browser cookies
- local browser profiles and run outputs
- machine-specific home-directory paths
- personal email addresses embedded in source files

CI enforces a repository hygiene scan in addition to tests, dependency audit, CodeQL, and Bandit.

## What It Does

- Runs up to 8 isolated Chrome profiles: `alpha` through `theta`.
- Uses a Linux "Desktop 2" through Xephyr, workspace mode, or the current display.
- Sends prompts to ChatGPT, Claude, Gemini, Grok, and Perplexity through browser UI automation.
- Supports session continuity, fresh-chat mode, browser pools, reserve browsers, and failover.
- Emits live completion progress with `colonia ask --progress`.
- Writes `report.md`, `result.json`, and an artifact directory for every run.
- Preserves fenced code blocks in markdown and saves them as `code-block-XX` files.
- Strips provider footer/upsell noise from stored replies.
- Can auto-select ChatGPT Web search or Deep research from prompt intent.
- Exposes local MCP tools/resources for other AI agents.

## When To Use It

Use Colonia when you want a local AI agent to consult multiple logged-in model products for research, review, planning, second opinions, or synthesis.

Colonia is not a replacement for official APIs when you need production SLAs, high throughput, or strict provider terms around automation. It is a local operator tool for personal research and agent-assisted consulting.

## Quick Start

Linux/X11 is required.

```bash
cd /path/to/colonia
python -m venv .venv
source .venv/bin/activate
pip install -e ".[dev]"
playwright install chromium

colonia init
colonia desktop start
colonia browsers launch --login
colonia browsers health
```

After `colonia browsers launch --login`, sign in once to the services you want to use in each Chrome profile.

Run a council query:

```bash
colonia ask \
  -p "Compare REST and GraphQL for a small B2B SaaS backend." \
  --browser beta,gamma \
  --service gemini,claude,grok,perplexity,chatgpt \
  --progress
```

Reports are written to:

```text
~/.colonia/runs/<job-id>/report.md
~/.colonia/runs/<job-id>/result.json
~/.colonia/runs/<job-id>/artifacts/
```

## Browser Profiles

Colonia defines eight browser slots by default.

| Browser | Default role |
| --- | --- |
| `alpha` | reserved/manual lane |
| `beta` | active default |
| `gamma` | active default |
| `delta` | active default |
| `epsilon` | active default |
| `zeta` | reserve/manual lane |
| `eta` | reserve/manual lane |
| `theta` | reserve/manual lane |

Useful commands:

```bash
colonia browsers launch
colonia browsers launch --name beta,gamma
colonia browsers launch --login
colonia browsers health
colonia browsers stop
```

By default, `--browser all` uses the active pool. Add `--all-browsers` to include reserve browsers.

## Desktop Modes

Colonia keeps the browser farm away from your main desktop.

| Mode | Description |
| --- | --- |
| `xephyr` | Nested X server on `DISPLAY=:20`; default and recommended |
| `workspace` | Uses `wmctrl` to move browsers to a Linux workspace |
| `current` | Uses your current display; useful for debugging |

```bash
colonia desktop start
colonia desktop start --mode workspace --workspace 1
colonia desktop status
colonia desktop stop
```

## Asking Models

Single service:

```bash
colonia ask -p "Give me a concise answer." --browser gamma --service gemini
```

Multiple services:

```bash
colonia ask \
  -p "Review this architecture decision and list failure modes." \
  --browser gamma \
  --service gemini,claude,grok,perplexity,chatgpt
```

Continue a thread across turns:

```bash
colonia ask -p "Remember token PROJECT_X." --session-id project-x --browser gamma --service gemini,grok
colonia ask -p "What token did I ask you to remember?" --session-id project-x --browser gamma --service gemini,grok
```

Force a new thread:

```bash
colonia ask -p "Start fresh." --fresh-chat --browser gamma --service chatgpt
```

## ChatGPT Web Search And Deep Research

Colonia can select ChatGPT tools before sending a prompt.

Automatic triggers:

- Deep research: prompts containing phrases like `deep research`, `thorough research`, `comprehensive research`, or `research report`.
- Web search: prompts containing phrases like `latest`, `current`, `today`, `this week`, or `as of now`.

Explicit tags:

```text
#deep-research
#web-search
#chatgpt-tool:deep-research
#chatgpt-tool:web-search
#chatgpt-tool:none
#no-chatgpt-tool
```

Deep research can take much longer than a normal reply. Use longer timeouts for those runs.

## Artifacts And Markdown

Every run stores model outputs in a markdown report and JSON file.

Colonia currently handles:

- Linked downloadable files exposed by provider pages.
- Fenced code blocks in model replies.
- Language-based file extensions for common code fences.
- Provider footer cleanup, including common ChatGPT upgrade/footer text.
- Unclosed code fences, which are closed before report output.

Example artifact path:

```text
~/.colonia/runs/<job-id>/artifacts/gamma/gemini/code/code-block-01.py
```

Markdown output details:

- `report.md` is human-readable and grouped by browser/service response.
- `result.json` is pretty-printed with stable indentation for machine use.
- fenced code blocks remain fenced in markdown and are also saved as separate files.
- provider footer noise is removed before report output is written.

## Model Plans

Model menus in consumer products change often. Colonia keeps model/profile plans inspectable:

```bash
colonia capabilities --json
colonia models plan --service gemini
colonia models apply --service gemini --dry-run
colonia models apply --service chatgpt
```

Use dry runs before applying model changes.

## MCP Server

Run the local MCP server:

```bash
colonia-mcp
```

The MCP surface exposes health, capabilities, browser launch/stop, and council ask operations for local agents.

## Configuration

Config lives at:

```text
~/.colonia/config.json
```

Example:

```json
{
  "data_dir": "/home/you/.colonia",
  "desktop": {
    "mode": "xephyr",
    "display": ":20",
    "workspace_index": 1,
    "width": 1920,
    "height": 1080
  },
  "browsers": [
    {
      "name": "alpha",
      "cdp_port": 9222,
      "profile_dir": "profiles/alpha",
      "enabled": true
    }
  ]
}
```

## Development

```bash
python -m venv .venv
source .venv/bin/activate
pip install -e ".[dev]"

python -m ruff format .
python -m ruff check .
python -m pyright .
python -m pytest --cov=colonia --cov-report=term-missing --cov-fail-under=80 -q
python -m build
pip-audit --skip-editable
python -m bandit -r colonia -x tests -ll
python scripts/check_repo_hygiene.py
```

## Security And Privacy Notes

- Colonia stores browser profiles and run outputs under `~/.colonia` by default.
- Do not commit `~/.colonia`, browser profiles, run outputs, cookies, or local databases.
- `.gitignore` excludes common local caches, runtime files, virtualenvs, build outputs, and env files.
- Review generated reports before sharing them; model replies may contain information from your prompts.
- Use separate browser profiles/accounts when testing risky prompts or untrusted content.
- See [SECURITY.md](SECURITY.md) for disclosure and release-hygiene guidance.

## Current Limits

- Live behavior depends on provider UI stability and account state.
- File upload support is service-dependent and incomplete.
- Consumer model labels and menus can change without notice.
- Deep research flows may exceed normal timeout settings.
- This is a local automation tool, not a hosted service.

## License

MIT. See [LICENSE](LICENSE).

## Legacy Utility

`perplexity_export.py` is a standalone legacy Perplexity history exporter that attaches through Chrome CDP.
