# EagleEye

AI-powered PR review for platform and data engineering teams. EagleEye combines **deterministic structural analysis** (blast radius, schema impact, security scan, lineage extract) with **five parallel specialist agents** and a **synthesis** step to produce actionable reviews.

**Distribution today:** CLI and MCP (Claude Code / Cursor). A hosted SaaS portal may follow later — the same review engine powers both.

---

## What it does

```
GitHub PR → fetch diff + files
         → pre-analysis (no LLM): blast radius, schema, security, lineage, EDP, tests
         → 5 specialist agents (parallel) + synthesis
         → verdict, findings, HTML/markdown report + Cockpit dashboard
```

| Mode | Best for | AI billing |
|------|----------|------------|
| **CLI** (`eagleeye review`) | Terminal, CI, full multi-agent pipeline | Your Anthropic API key or enterprise proxy |
| **MCP** (`eagleeye-mcp`) | Claude Code / Cursor chat | Host app's subscription (fetch tools); use `run_pr_review` when added for full pipeline |

---

## Requirements

- Python **3.11+** (3.12 recommended)
- **GitHub token** with `repo` scope (`read:org` for org repos)
- **Anthropic API key** for CLI reviews (`AUTH_MODE=direct`), or enterprise proxy (`AUTH_MODE=proxy`)

Optional: `pip install -e ".[lineage]"` for Snowflake snapshot enrichment (`pandas`, `snowflake-connector-python`).

---

## Install

```bash
git clone <your-private-repo-url>
cd eagleeye
python -m venv .venv
source .venv/bin/activate
pip install -e .
# optional: pip install -e ".[lineage]"
```

---

## Configure

Create `.env` in the project root (never commit this file):

```bash
AUTH_MODE=direct
GITHUB_TOKEN=ghp_...
ANTHROPIC_API_KEY=sk-ant-api03-...

# Optional tuning
EAGLEEYE_MODEL=claude-sonnet-4-6
EAGLEEYE_MAX_TOKENS=8192
```

Config priority: environment variables → `~/.eagleeye/config.yml` → `.env`.

Verify:

```bash
eagleeye config show
```

---

## First review (CLI)

```bash
eagleeye list-prs owner/repo
eagleeye review owner/repo 42
# or
eagleeye review https://github.com/owner/repo/pull/42

eagleeye review owner/repo 42 --usage    # token cost breakdown
eagleeye review owner/repo 42 --agents   # per-agent findings in terminal
```

Reviews are saved under `reviews/<owner>-<repo>/`.

---

## Dashboard (Cockpit)

```bash
eagleeye cockpit --open
```

Opens `reviews/index.html` — a static summary of all saved reviews. Per-PR HTML reports live alongside the markdown files.

---

## MCP setup (Claude Code)

Register EagleEye as an MCP server (GitHub token only in the server env; the host app provides the model):

```bash
eagleeye setup
```

Or add manually to Cursor / Claude config:

```json
{
  "mcpServers": {
    "eagleeye": {
      "command": "eagleeye-mcp",
      "env": {
        "GITHUB_TOKEN": "your_token"
      }
    }
  }
}
```

Start the server: `eagleeye-mcp`

**Note:** MCP tools today fetch PR data and blast radius; the **full multi-agent graph** runs via `eagleeye review` CLI. A `run_pr_review` MCP tool is planned so chat can trigger the same pipeline.

---

## Main commands

| Command | Description |
|---------|-------------|
| `eagleeye doctor` | Check install, tokens, config, and writable paths |
| `eagleeye review` | Full multi-agent PR review |
| `eagleeye read` | Repo architecture summary |
| `eagleeye audit` | Deterministic repo health checks (secrets, SQL injection, CI) |
| `eagleeye evaluate` | One-command repo evaluation — understanding, security, ratings, saved report |
| `eagleeye understand build` | Lightweight repo map (tree, README, signals) |
| `eagleeye scan` | Security / bug scan |
| `eagleeye list-prs` | List open PRs |
| `eagleeye cockpit` | Build/open review dashboard |
| `eagleeye lineage …` | Snowflake lineage snapshot tools (optional extra) |
| `eagleeye setup` | Register MCP in Claude Code |

---

## Optional: database lineage

```bash
pip install -e ".[lineage]"
export DB_SNAPSHOT_PATH=~/.eagleeye/lineage/object_dependencies_snapshot.json
eagleeye lineage refresh   # one-time Snowflake snapshot
```

Without the extra, regex-based Snowflake usage extraction still runs in reviews.

---

## Architecture (package layout)

```
eagleeye/
  core/           config, models, prompts, paths
  integrations/   github, anthropic
  graphs/         multi_agent review LangGraph
  workflows/      review persist, finalize
  servers/mcp/    MCP tools
  analysis/       structural pre-analysis
  lineage/        optional lineage facade
  presentation/   terminal + HTML reports
  storage/        context, history, reference indexes
```

---

## License & roadmap

Private repository. Open-source / SaaS decisions pending.

Internal planning docs live in `plan/` (local only in this commit phase).
