# Demo: the BDD gate driven by Claude Code

The scripted demo (`./scripts/demo_bdd_gate.sh`) proves the gate
deterministically. This scenario shows the same loop driven by a real AI
client: Claude implements, **Bisset evaluates** — the model never grades its
own homework.

Unlike the script, an LLM-driven session is not deterministic: the exact tool
calls and fixes may vary between runs. The gate behavior does not.

## Prerequisites

1. Bisset set up and the workflow server running:

   ```bash
   python3 -m venv .venv && source .venv/bin/activate
   pip install -r requirements.txt -r requirements-dev.txt
   ./scripts/server.sh start
   ```

2. The MCP server registered in Claude Code (once):

   ```bash
   claude mcp add bisset \
     -e WORKFLOW_BACKEND_URL=http://127.0.0.1:8765 \
     -- /absolute/path/to/BissetMCP/run-mcp.sh
   ```

3. A scratch copy of the demo project (so the repo copy stays buggy for the
   next demo):

   ```bash
   cp -r examples/demo/project /tmp/bisset-claude-demo
   ```

## The prompt

Start Claude Code anywhere, then paste:

```text
You have access to the "bisset" MCP tools. Use them — and only them — to manage
the workflow state. Target project: /tmp/bisset-claude-demo (a tiny calculator
with Gherkin acceptance criteria in features/calculator.feature).

1. Create a Bisset project for that path with test_runner
   "/absolute/path/to/BissetMCP/.venv/bin/behave", test_args "--format json",
   adapter "behave".
2. Start a session (workflow_type "new_feature") and add one step titled
   "Implement calculator" with feature_path "features/calculator.feature" and
   gate "tests_only".
3. Run the step tests with step_run_tests. Report the result honestly.
4. Whatever the result, immediately try step_complete and tell me what action
   Bisset returned and why you are (or are not) allowed to advance.
5. If you were blocked: read the failure feedback, fix the bug in the target
   project's code (do NOT touch the .feature file — it is the spec), re-run
   step_run_tests, and try step_complete again.
6. When the step advances, show me the pipeline_report.
```

## What you should observe

| Phase | Expected |
|-------|----------|
| First `step_run_tests` | 1 passed, 1 failed, scenario coverage 50% — `subtract()` is buggy |
| First `step_complete` | action `retry` (default rules) — **the gate blocks** |
| Claude's fix | `calc.py` corrected; the `.feature` file untouched |
| Second `step_run_tests` | 2 passed, 0 failed, coverage 100% |
| Second `step_complete` | action `advance`, session `completed` |

Key talking point: between the two `step_complete` calls, nothing changed in
Bisset's configuration — only the code changed. The acceptance decision came
from Bisset's own test execution, not from the model's claims.

## Reset for the next run

```bash
rm -rf /tmp/bisset-claude-demo
./scripts/db.sh delete-project <project_id>   # or: ./scripts/db.sh projects
```
