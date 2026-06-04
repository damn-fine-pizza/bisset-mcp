# BissetMCP

**Bisset** is a workflow orchestration server for AI-assisted software development, exposed as an [MCP](https://modelcontextprotocol.io) tool server. It guides a coding assistant through a structured, BDD-first development loop -- from requirements interview to executable, verified increments.

Bisset itself does **not** call any LLM API. It is a pure orchestration layer: it manages state, enforces gates, and exposes tools. The AI client (Claude, Copilot, etc.) does the thinking.

## Status

Bisset is an experimental prototype. It is a local-first MCP workflow controller for AI-assisted software development. It is not production-ready.

## Architecture

```
Any MCP client (Claude CLI, Copilot CLI, ...)
        |  STDIO (MCP protocol)
        v
  mcp_server  --HTTP-->  workflow_server  --SQLite-->  workflow.db
  (FastMCP)               (FastAPI :8765)
```

- **`mcp_server`** -- thin STDIO proxy; exposes all workflow operations as MCP tools and prompts.
- **`workflow_server`** -- stateful HTTP backend; owns the SQLite DB, the BDD runner, and all business logic.

## Quick start

```bash
# 1. Clone
git clone <repo-url> && cd BissetMCP

# 2. Create virtualenv + install deps
python3 -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt -r requirements-dev.txt

# 3. Copy config
cp .env.example .env

# 4. Start the workflow server (background, hot reload)
./scripts/server.sh start
```

The workflow server starts on `http://127.0.0.1:8765`. Check health:

```bash
curl http://127.0.0.1:8765/health
```

## Registering the MCP server

Bisset works with any MCP-compatible client. Below are the two primary targets.

### Claude CLI

```bash
claude mcp add bisset \
  -e WORKFLOW_BACKEND_URL=http://127.0.0.1:8765 \
  -- /absolute/path/to/BissetMCP/run-mcp.sh
```

Or use the helper:

```bash
./scripts/server.sh start mcp   # prints the exact command to copy-paste
```

### GitHub Copilot CLI

Add to your Copilot MCP config (`~/.config/github-copilot/mcp.json` or the VS Code equivalent):

```json
{
  "servers": {
    "bisset": {
      "type": "stdio",
      "command": "/absolute/path/to/BissetMCP/.venv/bin/python3",
      "args": ["-m", "orchestrator.mcp_server"],
      "env": {
        "PYTHONPATH": "/absolute/path/to/BissetMCP",
        "WORKFLOW_BACKEND_URL": "http://127.0.0.1:8765"
      }
    }
  }
}
```

> Replace `/absolute/path/to/BissetMCP` with the actual path on your machine.

### Docker

```bash
cp .env.example .env
docker compose up -d
```

The MCP server connects to the workflow server container automatically.

## Managing the database

Bisset stores all workflow state in SQLite. Use `scripts/db.sh` to inspect and manage it:

```bash
./scripts/db.sh projects                 # List all projects
./scripts/db.sh sessions                 # List all sessions
./scripts/db.sh sessions <project_id>    # Sessions for a project
./scripts/db.sh steps <session_id>       # Steps in a session
./scripts/db.sh events <session_id>      # Event log
./scripts/db.sh runs <step_id>           # Test run history
./scripts/db.sh detail <session_id>      # Full session overview

./scripts/db.sh delete-session <id>      # Delete a session (with confirmation)
./scripts/db.sh delete-project <id>      # Delete a project and all data
./scripts/db.sh reset                    # Wipe everything

./scripts/db.sh sql 'SELECT ...'         # Run arbitrary read-only SQL
./scripts/db.sh shell                    # Open sqlite3 shell
```

## Project structure

```
BissetMCP/
  orchestrator/
    mcp_server/          # MCP STDIO server (FastMCP)
    workflow_server/     # HTTP backend (FastAPI)
    tests/               # E2E tests
  adapters/
    claude.py            # Entry point for Claude
    copilot.py           # Entry point for Copilot
  scripts/
    server.sh            # Start/stop workflow server
    db.sh                # Database manager
  docs/                  # Design docs
  run-mcp.sh             # MCP STDIO server launcher (.venv-based)
  requirements.txt       # Runtime dependencies
  requirements-dev.txt   # Test + demo dependencies
  Dockerfile
  docker-compose.yml
```

## Demo: the BDD gate in action

A deterministic, self-contained demo of the core thesis — *Bisset is not a
test runner, it is a gatekeeper*. It spins up an isolated server, runs red
Gherkin scenarios, proves that acceptance is **blocked** while tests are red,
applies the fix, and shows acceptance succeeding:

```bash
python3 -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt -r requirements-dev.txt
./scripts/demo_bdd_gate.sh
```

Expected output: red tests → acceptance blocked → fix applied → green tests →
acceptance granted → session completed. The script exits non-zero if any of
those expectations fails (in particular, if the gate fails to block).

To run the same loop driven by an AI client instead of a script, see
[`examples/demo/claude-code-demo.md`](examples/demo/claude-code-demo.md).

## Running tests

```bash
PYTHONPATH=. pytest orchestrator/ -v
```

## Configuration

All variables are read from `.env` (copy `.env.example`):

| Variable                  | Default                                      | Description                          |
|---------------------------|----------------------------------------------|--------------------------------------|
| `DATABASE_PATH`           | `~/.bisset/bisset.db`                        | SQLite database file path            |
| `WORKFLOW_SERVER_PORT`    | `8765`                                       | HTTP port for the workflow server    |
| `WORKFLOW_BACKEND_URL`    | `http://127.0.0.1:8765`                      | URL the MCP proxy uses to reach backend |

Note on coverage: only the **behave** adapter reports a real (scenario-level)
coverage; pytest/generic adapters always report `0.0`. Coverage gating is
opt-in via session rules — see `docs/bdd-enforcement.md`.

## License

See [LICENSE](LICENSE).
