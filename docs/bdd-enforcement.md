# BDD Enforcement in Bisset (v2)

## Goal

Bisset enforces a **BDD-first development loop**: a pipeline step backed by a
Gherkin feature file cannot be accepted until Bisset itself has run the
scenarios and the session rules allow advancing.

The enforcement is **internal to Bisset** — not delegated to CI/CD or to the
LLM's self-reporting. Bisset executes the test runner as a subprocess and
stores the results. The LLM has no input path into the test results; it can
only influence outcomes by writing correct code.

Try it live: `./scripts/demo_bdd_gate.sh` (see the README "Demo" section).

---

## How the gate works

```
step_run_tests(step_id, session_id)
    ↓  Bisset executes: {test_runner} {test_args} {feature_path}   (cwd = project path)
    ↓  The adapter parses the output → passed, failed, coverage, errors
    ↓  Result stored in the test_runs table
step_complete(step_id, session_id)
    ↓  Bisset builds the rule context from ITS OWN stored results
    ↓  Rule engine evaluates when/then rules → action
    →  advance | retry | ask_user | abort | skip
```

`step_complete` never trusts the caller: it reads the latest `test_runs` row
recorded by `step_run_tests`. If no run exists, `no_tests` is true.

## Default rules

When neither the step (`rules_override`) nor the session (`default_rules`)
define rules, the engine applies these defaults:

```yaml
- when: no_tests                          # never accept without test evidence
  then: ask_user
- when: tests_pass AND gate == 'tests_only'
  then: advance
- when: tests_pass                        # human_approval / tests+human gates
  then: ask_user
- when: tests_fail AND retries < 3
  then: retry
- when: always
  then: ask_user
```

Red tests can never produce `advance` under the default rules. Sessions can
override this with `pipeline_set_rules` / `session_start(default_rules=...)`.

## Scenario coverage

The **behave adapter** computes real scenario coverage from behave's JSON
output: `coverage = passed_scenarios / total_scenarios * 100`.

The **pytest** and **generic** adapters do not compute coverage — they always
report `0.0`. For this reason, **coverage is intentionally absent from the
default rules**. If your project uses the behave adapter, you can opt in with
session rules, e.g.:

```yaml
- when: tests_pass AND coverage >= 80
  then: advance
```

There is no global coverage-threshold environment variable; thresholds live in
the rules of each session or step.

## Adapters

| Adapter   | Runner invocation                  | Counts                    | Coverage |
|-----------|------------------------------------|---------------------------|----------|
| `behave`  | `behave --format json --no-snippets <feature>`   | scenarios passed/failed   | scenario % |
| `pytest`  | `pytest <path>`                    | tests passed/failed       | always 0 |
| `generic` | any command, exit code only        | 1 pass or 1 fail          | always 0 |

Recommended `test_args` for behave projects: `--format json --no-snippets`.
With snippets enabled, behave corrupts its own JSON output when undefined
steps are present (verified on behave 1.3.3) and the adapter degrades to
exit-code-only parsing.

## Gherkin tools

| Tool | What it does |
|------|--------------|
| `step_set_feature` | Agent submits Gherkin; Bisset validates the structure, writes the file into `features_dir`, registers content + SHA-256 |
| `step_get_feature` | Reads the feature from disk (truth); reports `feature_drifted` / `file_missing` and realigns the registry |
| `step_validate_feature` | behave dry-run: `syntax_ok` and `steps_defined` as separate verdicts plus `undefined_steps[]` |

Drift policy: the human owns the spec. Manual edits never block execution;
they are detected (hash mismatch), reported in tool responses, logged as
`feature_drift` events (feature submissions are logged as `feature_set`), and the DB copy realigns to disk.

All adapter output is stripped of ANSI escape codes before being stored or
returned, so the model receives clean, structured feedback.

## Enforcement summary

| Actor | Role | Can lie? |
|-------|------|----------|
| LLM (Claude/Copilot) | Writes feature files, step defs, production code | Yes — but feature files are on disk |
| Bisset `step_run_tests` | Executes runner, parses output, stores results | No — executes independently |
| Bisset `step_complete` | Evaluates rules against its own DB results | No — checks its own DB |
| CI (optional) | Re-runs all features on push | No — independent execution |

## Limitations

- The project path must be accessible from the machine running `workflow_server`.
- The test runner must be installed and reachable (use an absolute path for
  virtualenv runners, e.g. `/path/to/.venv/bin/behave`).
- Coverage is measured at **scenario level** (passed/total), not at code line
  level, and only by the behave adapter.
- A step without `feature_path` produces `no_tests` → `ask_user` under the
  default rules (graceful degradation, never silent acceptance).
