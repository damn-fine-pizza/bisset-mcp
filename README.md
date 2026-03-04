# Bisset MCP

**Bisset** is a workflow orchestration server for AI-assisted software development, exposed as an [MCP](https://modelcontextprotocol.io) tool server. It guides a coding assistant (e.g. GitHub Copilot CLI) through a structured, BDD-first development loop — from requirements interview to executable, verified increments.

## What it does

1. **Requirements interview** — Bisset asks a structured set of questions about the project. The assistant collects answers from the user and records them.
2. **Spec freeze** — answers are locked into a specification document, an ADR stub, and a work breakdown.
3. **Execution loop** — tasks are delivered one at a time. Each task can carry Gherkin acceptance criteria. Bisset writes the `.feature` file to the project repo and, when the assistant calls `workflow_run_tests`, executes the BDD runner itself and stores the results. A task cannot be marked done unless its scenarios pass the coverage threshold (default: 80%).

The assistant speaks to the user in any language. All data written to the workflow database is in English.

## Architecture

```
Copilot CLI (or any MCP client)
        │  STDIO (MCP protocol)
        ▼
  mcp_server  ──HTTP──►  workflow_server  ──SQLite──►  bisset-db/
  (FastMCP)               (FastAPI :8765)
```

- **`mcp_server`** — thin STDIO proxy; exposes all workflow operations as MCP tools and prompts.
- **`workflow_server`** — stateful HTTP backend; owns the SQLite DB, the BDD runner, and all business logic.

## Tools exposed to the assistant

| Tool | Description |
|------|-------------|
| `workflow_new_session` | Create a new project session |
| `workflow_switch_session` | Switch to an existing session |
| `workflow_start` | Seed the question catalog and begin the interview |
| `workflow_next_question` | Get the next unanswered question |
| `workflow_record_answer` | Record an answer |
| `workflow_freeze_spec` | Lock the spec and generate work breakdown |
| `workflow_next_task` | Get the current pending task (with Gherkin criteria) |
| `workflow_add_task` | Add a project-specific task with Gherkin acceptance criteria |
| `workflow_run_tests` | **Bisset runs the BDD tests** — no self-reporting |
| `workflow_accept_task_result` | Mark a task done (gated on test results) |
| `workflow_list_tasks` | List all tasks and their status |
| `workflow_list_questions` | List all questions and answers |
| `workflow_list_sessions` | List all sessions |
| `workflow_report` | Summary of current phase and progress |
| `workflow_is_done` | Check if all tasks are complete |

## BDD enforcement

When a task has `acceptance_criteria`:

1. `workflow_add_task` writes `{project_path}/features/{task_id}.feature` automatically.
2. The assistant implements the feature.
3. `workflow_run_tests(task_id)` — Bisset executes the configured runner (`pytest`, `behave`, etc.) in `project_path` and stores pass/fail counts. The assistant has no input path into results.
4. `workflow_accept_task_result` is **blocked** unless a passing run exists in the DB with `coverage_pct >= bdd_coverage_threshold` (default 80%).

See [`docs/bdd-enforcement.md`](docs/bdd-enforcement.md) for full design.

## Quick start

```bash
# 1. Install dependencies
cd orchestrator
pip install -r workflow_server/requirements.txt

# 2. Start the workflow server
python -m orchestrator.workflow_server

# 3. Start the MCP server (in a separate terminal or via your MCP client config)
python -m orchestrator.mcp_server
```

Or use the provided script:

```bash
./start.sh
```

### MCP client configuration (Copilot CLI)

```json
{
  "mcpServers": {
    "bisset": {
      "command": "python",
      "args": ["-m", "orchestrator.mcp_server"],
      "cwd": "/path/to/BissetMCP"
    }
  }
}
```

### Project meta (BDD runner config)

Pass these in `workflow_start` to enable BDD enforcement:

```json
{
  "name": "MyProject",
  "project_path": "/absolute/path/to/project",
  "features_dir": "features",
  "test_runner": "pytest",
  "test_runner_args": ["--tb=short", "-q"],
  "bdd_coverage_threshold": 80
}
```

## Running tests

```bash
pytest features/ --ignore=features/steps/test_mcp_stdio.py
```

## Repository layout

```
orchestrator/
  mcp_server/         # STDIO MCP proxy
  workflow_server/    # FastAPI backend
    app.py            # HTTP endpoints + prompts
    engine.py         # business logic
    storage.py        # SQLite persistence
    catalog.py        # default questions + tasks
    renderers.py      # spec/plan/feature file writers
docs/
  architecture.md
  bdd-enforcement.md
features/             # BDD tests for Bisset itself
```

## License

GNU General Public License v3.0 — see [LICENSE](LICENSE).
