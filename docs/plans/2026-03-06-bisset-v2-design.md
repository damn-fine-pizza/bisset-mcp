# Bisset v2 — Design Document

**Date:** 2026-03-06
**Status:** Approved
**Approach:** Evolutionary refactor (keeps FastAPI + SQLite + HTTP client + server.sh)

## Objective

Bisset is an MCP workflow orchestrator that guides Claude (and in the future Copilot) through user-defined development pipelines. Each pipeline step is validated by Gherkin tests executed by Bisset. Claude implements, Bisset evaluates. The loop converges when all scenarios pass and coverage exceeds the threshold.

The .feature is the reward function. Claude is the agent. The code is the policy. Bisset is the environment. Each retry is an episode. Coverage is the score.

## Architecture

```
Claude Code (or Copilot)
        |  STDIO (MCP protocol)
        v
  mcp_server  --HTTP-->  workflow_server  --SQLite-->  ~/.bisset/bisset.db
  (adapter)               (FastAPI :8765)
                                |
                                v
                          Test Runner
                          (subprocess: pytest/behave/cucumber)
```

- **mcp_server** — thin STDIO adapter, translates MCP tool calls into HTTP
- **workflow_server** — all the logic: rule engine, gate, test execution
- **bisset.db** — central DB at `~/.bisset/bisset.db`, contains all projects

Zero logic in the FastAPI endpoints. Everything in the engine.

## Data Model

```
PROJECT
  id, name, path, created_at
  test_runner, test_args, adapter, features_dir

SESSION
  id, project_id, created_at
  workflow_type: new_project | new_feature | generate_tests
  status: active | paused | completed | aborted
  default_rules (JSON — DSL rules)

STEP
  id, session_id, title, description, order
  feature_path (path to the .feature file)
  gate: tests_only | human_approval | tests+human
  depends_on (JSON — list of step_id)
  rules_override (JSON — rules specific to this step)
  status: pending | active | passed | failed | skipped
  retries, current_coverage
  gate_result: null | approved | rejected

TEST_RUN
  id, step_id, session_id
  run_at, passed, failed, coverage
  runner_output (full log)

EVENT
  id, session_id, timestamp
  event_type, step_id
  data (JSON)
```

### Project Isolation

- Central DB: `~/.bisset/bisset.db`
- Cross-project reads allowed (project_list, session_list of other projects)
- Writes only on the locked project — every tool that modifies state uses the implicit project_id from the lock
- No operational tool accepts project_id as a parameter
- To switch projects: `project_switch` (closes lock, reopens)
- On open: verifies that the path in the DB matches the cwd

## MCP Tools

### Project

| Tool | Type | Description |
|------|------|-------------|
| `project_detect` | read | Autodetect project from cwd |
| `project_create` | write | Create new project, lock it |
| `project_list` | read | List all projects in the DB |
| `project_switch` | write | Switch active project |

### Session

| Tool | Type | Description |
|------|------|-------------|
| `session_start` | write | Create session, choose workflow_type |
| `session_resume` | write | Resume last session, copy step state |
| `session_status` | read | Status: steps, progress, current step |
| `session_list` | read | List sessions of a project (cross-project ok) |

### Pipeline

| Tool | Type | Description |
|------|------|-------------|
| `step_current` | read | Active step: description, .feature, criteria |
| `step_run_tests` | write | Bisset runs Gherkin tests, returns result |
| `step_complete` | write | Attempt to close the step (gate check + DSL rules) |
| `step_skip` | write | Skip with mandatory reason |
| `step_list` | read | List all steps with status |
| `step_add` | write | Add step (title, description, gate, position) |
| `step_remove` | write | Remove step (only if pending) |
| `step_edit` | write | Edit title/description/gate/feature |
| `step_reorder` | write | Change order and dependencies |
| `pipeline_view` | read | Full pipeline with status and dependencies |
| `pipeline_set_rules` | write | Modify session DSL rules |

### Gherkin

| Tool | Type | Description |
|------|------|-------------|
| `step_set_feature` | write | Claude sends Gherkin content, Bisset saves to disk and DB |
| `step_get_feature` | read | Read the current .feature of a step |
| `step_validate_feature` | read | Dry-run: verify Gherkin syntax without executing |

### Interview

| Tool | Type | Description |
|------|------|-------------|
| `interview_answer` | write | Answer the current question, receive the next one |

### Analysis

| Tool | Type | Description |
|------|------|-------------|
| `analyze_codebase` | write | Analyze existing project, generate steps + .feature |

### Introspection

| Tool | Type | Description |
|------|------|-------------|
| `pipeline_report` | read | Report: completed, failed, coverage, time |
| `event_log` | read | Session audit trail |

## Rule Engine DSL

Declarative when/then rules, evaluated in order. First match wins.

### Variables

| Variable | Type | Description |
|-----------|------|-------------|
| `tests_pass` | bool | All tests passed |
| `tests_fail` | bool | At least one test failed |
| `coverage` | float | Coverage percentage from last run |
| `retries` | int | Number of times the step has been retried |
| `gate` | string | Gate type of the step |
| `no_tests` | bool | No .feature associated |
| `step.order` | int | Position in the pipeline |
| `always` | bool | Always true (fallback) |

### Actions

| Action | Effect |
|--------|---------|
| `advance` | Step done, move to next |
| `retry` | Step returns to active, increment retries |
| `ask_user` | Ask user for confirmation |
| `abort` | Stop the pipeline |
| `skip` | Skip the step |

### Example

```yaml
rules:
  - when: tests_pass AND coverage >= 80
    then: advance
  - when: tests_fail AND retries < 3
    then: retry
  - when: tests_fail AND retries >= 3
    then: ask_user
  - when: tests_pass AND gate == "human_approval"
    then: ask_user
  - when: no_tests
    then: ask_user
  - when: always
    then: abort
```

Each session has `default_rules`. Each step can have `rules_override`.

## Workflow Types

### new_project

```
1. interview  — questions about scope, stack, constraints
2. design     — Claude proposes architecture, user approves
3. generate   — Claude generates steps + .feature for each component
4. execute    — step-by-step gated: implement -> test -> advance
```

### new_feature

```
1. analyze    — Claude analyzes existing codebase
2. interview  — targeted questions about the feature
3. generate   — Claude generates steps + .feature for the feature
4. execute    — step-by-step gated
```

### generate_tests

```
1. analyze    — Claude analyzes codebase (API, models, logic, UI)
2. generate   — Claude generates .feature for everything
3. validate   — Bisset runs tests, reports what passes and what doesn't
```

The phases are meta-steps that produce the concrete steps. Once generated, the session only has steps — the phases disappear. The user can modify the generated steps before executing them.

## Test Runner and Adapter

Bisset runs the tests autonomously. Claude does not touch the results.

```
step_run_tests
  -> reads feature_path of the step
  -> subprocess.run([test_runner, feature_path, *test_args])
  -> adapter parses output
  -> saves to DB: passed, failed, coverage, raw output
  -> applies DSL rules
  -> returns action to Claude
```

### Adapter

```python
class AdapterResult:
    passed: int
    failed: int
    coverage: float
    errors: list[str]
    raw_output: str
```

| Adapter | Runner | Parsing |
|---------|--------|---------|
| `pytest` | `pytest --tb=short -q` | Exit code + stdout |
| `behave` | `behave --format json` | Native JSON |
| `cucumber` | `cucumber --format json` | Native JSON |
| `generic` | Any command | Exit code only |

## MCP Resources

Read real data from the DB:

| URI | Content |
|-----|-----------|
| `project://current` | Active project: name, path, config |
| `session://current` | Session: workflow_type, status, progress |
| `pipeline://current` | Steps with status, dependencies, rules |
| `history://sessions` | Previous sessions of the project |

## MCP Prompts

Static templates + dynamic variables (from DB and Claude context):

| Prompt | Phase |
|--------|------|
| `bisset/interviewer` | interview |
| `bisset/architect` | design |
| `bisset/analyzer` | analyze |
| `bisset/implementer` | execute |
| `bisset/test-writer` | generate |

### Prompt Composition

Templates with `{{...}}` variables:
- **DB variables** (auto): `step.*`, `project.*`, `session.*`
- **Context variables** (from Claude): `context.directory_structure`, `context.patterns`, `context.relevant_files`

Claude calls `prompt_load("bisset/implementer", context={...})` passing the context variables. Bisset merges DB + context and returns the composed prompt.

## Convergence Loop

```
Claude generates code
    |
Bisset runs .feature (step_run_tests)
    |
Result: 3/5 pass, coverage 60%
    |
DSL rules: retry (coverage < 80)
    |
Claude receives structured feedback: "scenarios X and Y failed because Z"
    |
Claude corrects
    |
Bisset runs .feature
    |
5/5 pass, coverage 100% -> advance
```

Early stopping: `retries >= 3 -> ask_user`. If Claude does not converge, a human is needed.

## What to Keep from the Current Code

| Component | Action |
|-----------|--------|
| `storage.py` | Rewrite schema, keep migration system |
| `app.py` | Rewrite endpoints, keep FastAPI + ResponseWrapper |
| `client.py` | Keep, update tool mapping |
| `server.sh` | Keep (hot reload + color logging already done) |
| `engine.py` | Rewrite completely (rule engine + gate logic) |
| `server.py` | Rewrite with official MCP SDK |
| `prompts.py` | Rewrite as template system |

## What to Remove

- ComplexityAnalyzer / model routing
- 20 `.agent.md` files (Copilot-specific)
- Hardcoded question catalog
- Background jobs / async mode
- Static prompts for hardcoded phases
