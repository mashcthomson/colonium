# Colonium

Colonium is a local, non-API LLM council for research and technical consulting.

It drives your own logged-in ChatGPT, Claude, Gemini, Grok, and Perplexity
browser sessions, sends the same prompt to selected services, and saves the
results as Markdown, JSON, and artifacts. It is a local controller, not a local
AI model: any developer, script, or AI agent that can call a CLI or MCP tool can
use it.

Colonium is useful when you want several consumer LLM products to review a
question, plan, research task, or code approach without sending prompts, cookies,
or API keys to a hosted orchestration service.

## What Colonium Does

- Opens and manages multiple isolated Chrome profiles.
- Sends prompts to ChatGPT, Claude, Gemini, Grok, and Perplexity.
- Supports single-model asks, multi-model councils, session continuation, and
  fresh-chat mode.
- Runs up to eight named browser lanes: `alpha` through `theta`.
- Saves each run to `report.md`, `result.json`, and an `artifacts/` directory.
- Preserves fenced code blocks in Markdown and exports them as separate files.
- Downloads linked files when provider pages expose downloadable artifacts.
- Removes common footer, upsell, and ad-like provider noise before reports are
  written.
- Can select ChatGPT Web Search or Deep Research from prompt intent or tags.
- Exposes a local MCP server so other AI agents can use Colonium as a tool.

## What It Is Not

- It is not a hosted product.
- It is not an official model API wrapper.
- It is not a local/offline LLM runtime.
- It is not meant for high-volume scraping or production workloads needing SLAs.

For production throughput, strict compliance, or guaranteed availability, use the
official provider APIs.

## OS And Desktop Support

Colonium is designed around Chrome plus Playwright/CDP, so the core browser
control path can run on macOS, Linux, and Windows when Chrome is available.

Linux is the best-tested environment and has the most desktop isolation options.
macOS and Windows should use `current` mode, which opens the browser profiles on
the normal desktop.

| Mode | OS | What it does |
| --- | --- | --- |
| `current` | macOS, Linux, Windows | Uses the current desktop with no isolation. |
| `xephyr` | Linux only | Starts a nested X server for an isolated browser desktop. |
| `workspace` | Linux only | Sends windows to an existing workspace with `wmctrl`. |

Xephyr is optional. It is the default on Linux because it keeps the browser farm
away from your main desktop, but it is not required for Colonium to work.

## Requirements

- Python 3.11 or newer
- Google Chrome or Chromium
- Playwright browser dependencies
- Logged-in accounts for the model products you want to use

Linux optional packages:

- `xserver-xephyr` for `xephyr` mode
- `wmctrl` for `workspace` mode
- a lightweight window manager such as `openbox` for the nested desktop

If Chrome is not on your PATH, set `desktop.chrome_binary` in
`~/.colonium/config.json`.

## Install From Source

macOS/Linux:

```bash
git clone https://github.com/mashcthomson/colonium.git
cd colonium

python -m venv .venv
source .venv/bin/activate
pip install -e ".[dev]"
playwright install chromium
```

Windows PowerShell:

```powershell
git clone https://github.com/mashcthomson/colonium.git
cd colonium

py -m venv .venv
.\.venv\Scripts\Activate.ps1
pip install -e ".[dev]"
playwright install chromium
```

Initialize local state:

```bash
colonium init
```

This creates `~/.colonium/config.json` and runtime directories under
`~/.colonium/`.

## First Run

Start the desktop mode:

```bash
colonium desktop start
```

On macOS or Windows, use current mode if an existing config still points at a
Linux-only mode:

```bash
colonium desktop start --mode current
```

Launch browser profiles and open the login pages:

```bash
colonium browsers launch --login
```

Sign in to the services you want to use. Login state stays in local Chrome
profiles under `~/.colonium/profiles/`.

Check browser health:

```bash
colonium browsers health
```

## Run A Council Query

Ask several services from one browser profile:

```bash
colonium ask \
  --browser beta \
  --service gemini,claude,grok,perplexity,chatgpt \
  --progress \
  -p "Review this backend architecture and list the main failure modes."
```

Ask across several browser profiles:

```bash
colonium ask \
  --browser beta,gamma,delta \
  --service gemini,claude,grok \
  --progress \
  -p "Compare these implementation options and recommend the safest one."
```

Use all configured browser lanes, including reserve lanes:

```bash
colonium ask \
  --browser all \
  --all-browsers \
  --service chatgpt,claude,gemini \
  -p "Summarize the trade-offs in this plan."
```

## Outputs

Each run creates a folder under `~/.colonium/runs/<job-id>/`.

```text
~/.colonium/runs/<job-id>/
  report.md
  result.json
  artifacts/
```

`report.md` is the readable council report. It includes the prompt, summary
counts, provider URLs, model labels when available, errors, artifact links, and
each response grouped by browser and service.

`result.json` is the structured run result for scripts and agents.

`artifacts/` contains downloaded files and extracted code blocks. Fenced code
blocks are preserved in the report and saved with language-based extensions when
possible:

```text
~/.colonium/runs/<job-id>/artifacts/beta/chatgpt/code/code-block-01.py
```

Colonium writes Markdown, not R Markdown. If a provider returns R or R Markdown
code fences, those fences are preserved and exported like other code artifacts.

## Progress And Long Research Runs

Use `--progress` when running many browsers or slow tools:

```bash
colonium ask --browser all --all-browsers --progress -p "..."
```

The CLI prints completed browser/service batches to stderr while other tasks are
still pending. The final `result.json` also stores progress events, so an agent
can see which model replies finished and which ones were still pending during the
run.

Deep Research can take much longer than a normal reply. Use a longer timeout for
those runs:

```bash
colonium ask \
  --service chatgpt,perplexity \
  --timeout 1800000 \
  -p "#deep-research Produce a cited market scan for ..."
```

## Session Continuation

Use `--session-id` to continue related turns across services:

```bash
colonium ask \
  --session-id design-review-1 \
  --browser gamma \
  --service claude,gemini \
  -p "Remember this context: we are reviewing the billing service."

colonium ask \
  --session-id design-review-1 \
  --browser gamma \
  --service claude,gemini \
  -p "Given that context, what are the riskiest edge cases?"
```

Force a new thread:

```bash
colonium ask --fresh-chat --browser gamma --service chatgpt -p "Start fresh."
```

## ChatGPT Tools And Prompt Skills

Colonium can select ChatGPT Web Search or Deep Research before sending a prompt.

Automatic triggers:

- Web Search: `latest`, `current`, `today`, `this week`, `as of now`
- Deep Research: `deep research`, `thorough research`, `comprehensive research`,
  `research report`

Explicit tags:

```text
#web-search
#deep-research
#chatgpt-tool:web-search
#chatgpt-tool:deep-research
#chatgpt-tool:none
#no-chatgpt-tool
```

Prompt skill presets are also exposed through the capability payload. Examples
include quick answers, quick web checks, Reddit/community scans, citation-heavy
answers, contrarian review, consensus synthesis, and reflective review.

## Model Choice Strategy

Colonium treats the eight browser lanes as model lanes. This lets a caller ask
different services, models, and effort levels for different kinds of judgment.

Inspect the current plan:

```bash
colonium models plan
colonium models plan --service chatgpt
colonium models plan --service perplexity --browser beta,gamma,delta
```

Dry-run model changes before applying them:

```bash
colonium models apply --service claude --dry-run
```

The public capability payload includes the model plan and caveats:

```bash
colonium capabilities --json
```

Current lanes include combinations such as:

- Claude Sonnet lanes with medium, high, max, and thinking-style assignments.
- Gemini Flash, Flash-Lite, and Pro lanes with standard or extended thinking.
- Grok Fast, Auto, Expert, and Heavy lanes.
- Perplexity search, deep research, model council, and learn-step-by-step lanes.
- ChatGPT Web Search lanes plus reserved/manual Deep Research lanes.

Provider UIs change often. Treat `models plan` as the intended layout and verify
live UI state before relying on a lane for critical work.

## Browser Profiles

Colonium ships with eight named browser slots.

| Browser | Default pool |
| --- | --- |
| `alpha` | active, skipped by default for now |
| `beta` | active |
| `gamma` | active |
| `delta` | active |
| `epsilon` | active |
| `zeta` | reserve |
| `eta` | reserve |
| `theta` | reserve |

Useful commands:

```bash
colonium browsers launch
colonium browsers launch --name beta,gamma
colonium browsers launch --login
colonium browsers health
colonium browsers stop
```

By default, `--browser all` uses the active pool. Add `--all-browsers` to include
reserve browsers.

## MCP Server

Run the local MCP server:

```bash
colonium-mcp
```

The MCP server exposes:

- `colonium_capabilities`
- `colonium_health`
- `colonium_ask`
- `colonium_model_plan`
- `colonium_model_apply`
- `colonium://capabilities`
- `colonium://config`

This is the recommended integration point for other AI coding agents. The agent
does not need model-provider API keys; it asks Colonium to operate your local
browser sessions.

## Configuration

The default config file is:

```text
~/.colonium/config.json
```

Example:

```json
{
  "data_dir": "/home/you/.colonium",
  "desktop": {
    "mode": "current",
    "display": ":20",
    "workspace_index": 1,
    "width": 1920,
    "height": 1080,
    "chrome_binary": "google-chrome"
  },
  "browsers": [
    {
      "name": "alpha",
      "cdp_port": 9222,
      "profile_dir": "profiles/alpha",
      "enabled": true,
      "pool": "active"
    }
  ]
}
```

On macOS, `chrome_binary` can be:

```text
/Applications/Google Chrome.app/Contents/MacOS/Google Chrome
```

On Windows, use `chrome.exe` if it is on PATH or set the full Chrome executable
path.

## Privacy And Security

Colonium is local-first, but it still handles sensitive local state.

- Browser cookies and login state live under `~/.colonium/profiles/`.
- Run reports and artifacts live under `~/.colonium/runs/`.
- Generated reports may contain prompt text, model replies, links, and downloaded
  files.
- Do not commit `~/.colonium`, browser profiles, cookies, local databases, or
  generated run outputs.
- Review `report.md`, `result.json`, and artifacts before sharing them.
- Use separate browser accounts or profiles for risky prompts.

The repository includes a hygiene scan for obvious secrets, personal email
addresses, and machine-specific home paths:

```bash
python scripts/check_repo_hygiene.py
```

See [SECURITY.md](SECURITY.md) for supported security reporting and release
hygiene.

## Development

```bash
python -m venv .venv
source .venv/bin/activate
pip install -e ".[dev]"

python -m ruff format .
python -m ruff check .
python -m pyright .
python -m pytest --cov=colonium --cov-report=term-missing --cov-fail-under=80 -q
python -m build
pip-audit --skip-editable
python -m bandit -r colonium scripts perplexity_export.py -x tests -ll
python scripts/check_repo_hygiene.py
```

GitHub Actions runs linting, type checking, tests, package build, dependency
audit, Bandit, CodeQL, and repository hygiene checks.

## Limitations

- Provider UIs change without notice. Selectors and model names may need updates.
- Account state matters. Rate limits, modals, onboarding screens, and plan limits
  can affect runs.
- macOS and Windows support uses current-desktop mode; Linux has the strongest
  isolation story today.
- File upload support is not complete across all providers.
- Browser automation may not fit every provider's terms. Use official APIs for
  production or high-volume workloads.
- Colonium is alpha software. Validate important outputs before acting on them.

## License

Colonium is released under the MIT License. See [LICENSE](LICENSE).
