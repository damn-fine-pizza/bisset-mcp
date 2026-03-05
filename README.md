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

## Agent hierarchy

```mermaid
flowchart TD
    User((User)) --> bisset

    bisset -->|Phase 2| bi[bisset-interview]
    bisset -->|Phase 2.5| br[bisset-requirements]
    bisset -->|Phase 3| ba[bisset-architect]
    bisset -->|Phase 4 & 6| btg[bisset-test-gherkin]
    bisset -->|Phase 5| bim[bisset-implement]
    bisset -->|Any phase| brev[bisset-review]

    ba --> ba_oop[bisset-architect-oop]
    ba --> ba_fn[bisset-architect-functional]
    ba --> ba_dod[bisset-architect-dataoriented]
    ba --> br

    brev --> br

    bim --> bback[bisset-backend]
    bim --> bfront[bisset-frontend]
    bim --> bemb[bisset-embedded]
    bim --> bux[bisset-ux]
    bim --> bdb[bisset-database]
    bim --> bcloud[bisset-cloud]
    bim --> bdevops[bisset-devops]
```

### Phase sequence

```
Phase 1   → bisset           session creation
Phase 2   → bisset-interview requirements interview
Phase 2.5 → bisset-requirements validate completeness / consistency / testability
              └─ requirements_incomplete → loop back to Phase 2
Phase 3   → bisset-architect  evaluate OOP / Functional / Data-Oriented proposals
              ├─ bisset-architect-{oop,functional,dataoriented}  produce proposals
              │    ⚠️  these 3 sub-agents run sequentially (Copilot CLI limitation — no
              │        native parallelism). Phase 3 takes ~3× longer than other phases.
              │        If time is critical, a human operator can run the three agents
              │        manually in separate sessions and paste proposals into the chat.
              └─ bisset-requirements  cross-check architectural coverage
Phase 4   → bisset-test-gherkin  generate {task}.feature + {task}.negative.feature
Phase 5   → bisset-implement  implement task by task via domain specialists
Phase 6   → bisset-test-gherkin  run full BDD suite, gate on > 80% coverage
              └─ coverage_failed → loop back to Phase 5
Review    → bisset-review     conformance audit (any time)
              └─ no requirements? → bisset-requirements extracts them from code
```

### Agent table

| Agent | Phase | user-invocable | Parent | Key tools |
|---|---|---|---|---|
| `bisset` | dispatcher | ✅ | — | agent, workflow_get_state |
| `bisset-interview` | 2 | ❌ | bisset | workflow tools |
| `bisset-requirements` | 2.5 / 3 / review | ❌ | bisset, bisset-architect, bisset-review | agent |
| `bisset-requirements-validate` | 2.5 | ❌ | bisset-requirements | workflow_advance_phase |
| `bisset-requirements-extract` | review | ❌ | bisset-requirements | workflow_store_proposal |
| `bisset-architect` | 3 | ❌ | bisset | agent, workflow_advance_phase, workflow_list_proposals |
| `bisset-architect-oop` | 3 | ❌ | bisset-architect | workflow_store_proposal |
| `bisset-architect-functional` | 3 | ❌ | bisset-architect | workflow_store_proposal |
| `bisset-architect-dataoriented` | 3 | ❌ | bisset-architect | workflow_store_proposal |
| `bisset-test-gherkin` | 4, 6 | ❌ | bisset | workflow_advance_phase, workflow_add_task |
| `bisset-implement` | 5 | ❌ | bisset | agent, workflow_advance_phase, workflow_run_tests |
| `bisset-backend` | 5 | ❌ | bisset-implement | read, edit, execute |
| `bisset-frontend` | 5 | ❌ | bisset-implement | read, edit, execute |
| `bisset-embedded` | 5 | ❌ | bisset-implement | read, edit, execute |
| `bisset-ux` | 5 | ❌ | bisset-implement | read, edit |
| `bisset-database` | 5 | ❌ | bisset-implement | read, edit, execute |
| `bisset-cloud` | 5 | ❌ | bisset-implement | read, edit, execute |
| `bisset-devops` | 5 | ❌ | bisset-implement | read, edit, execute |
| `bisset-review` | any | ❌ | bisset | agent, execute, workflow_list_tasks |

## Tools exposed to the assistant

| Tool | Description |
|------|-------------|
| `workflow_new_session` | Create a new project session |
| `workflow_switch_session` | Switch to an existing session |
| `workflow_start` | Seed the question catalog and begin the interview |
| `workflow_next_question` | Get the next unanswered question |
| `workflow_record_answer` | Record an answer |
| `workflow_freeze_spec` | Lock the spec and generate work breakdown |
| `workflow_advance_phase` | Emit a signal to advance the workflow sub-phase |
| `workflow_next_task` | Get the current pending task (with Gherkin criteria) |
| `workflow_add_task` | Add a project-specific task with Gherkin acceptance criteria |
| `workflow_run_tests` | **Bisset runs the BDD tests** — no self-reporting |
| `workflow_accept_task_result` | Mark a task done (gated on test results) |
| `workflow_list_tasks` | List all tasks and their status |
| `workflow_list_questions` | List all questions and answers |
| `workflow_list_sessions` | List all sessions |
| `workflow_report` | Summary of current phase and progress |
| `workflow_is_done` | Check if all tasks are complete |
| `workflow_store_proposal` | Persist an architecture proposal for the session |
| `workflow_list_proposals` | Retrieve stored architecture proposals |

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
  "bdd_coverage_threshold": 80,
  "use_line_coverage": true,
  "line_coverage_threshold": 80
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
