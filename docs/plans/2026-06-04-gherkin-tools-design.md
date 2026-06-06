# Gherkin Tools — Design Document

**Date:** 2026-06-04
**Status:** Implemented
**Scope:** Approach B, first slice — the three Gherkin tools from the v2 design
(`step_set_feature`, `step_get_feature`, `step_validate_feature`).

## Objective

Move the feature-authoring flow from "the agent writes `.feature` files by
hand on disk" to "the agent hands the Gherkin to Bisset, which validates,
persists, and audits it". The `.feature` is the contract; Bisset becomes its
custodian without taking ownership away from the human.

Out of scope (deferred): `interview_answer`, `analyze_codebase`, workflow
phases, workflow packs.

## Decisions

1. **Ownership: disk = truth, DB = registry.** Bisset writes the file into the
   target project's `features_dir` (committable in git, readable by the
   runner) and keeps content + SHA-256 hash in its DB for audit and drift
   detection.
2. **Validation: one mechanism, two verdicts.** A single `behave --dry-run`
   produces both a syntax verdict and a step-definition verdict. The response
   keeps them separate (`syntax_ok`, `steps_defined`) because they demand
   different corrective actions from the agent (fix the Gherkin vs write glue
   code).
3. **Drift: detect and report, disk wins.** If the file on disk no longer
   matches the registered hash, Bisset proceeds (the human owns the spec) but
   flags `feature_drifted: true`, logs a `feature_drift` event, and refreshes
   the DB copy.

## Tools

| Tool | Type | Contract |
|------|------|----------|
| `step_set_feature(step_id, content, filename?)` | write | Validate syntax; on success write to `{project.path}/{features_dir}/{filename}` (default filename derived from the step title), store content + hash on the step, set `feature_path`, log `feature_set` event. On syntax error: structured error, **no file written**. |
| `step_get_feature(step_id)` | read | Read the file **from disk** (truth). Respond with content, `feature_drifted`, and `file_missing`. On drift: refresh the DB copy and log `feature_drift`. On missing file: return last DB copy as reference. |
| `step_validate_feature(step_id)` | read | Run `behave --dry-run --format json` against the step's feature. Respond `{syntax_ok, steps_defined, undefined_steps[], errors[]}`. |

All three are exposed at both layers following the existing flat pattern:
FastAPI endpoint `/{tool_name}` + MCP tool with matching schema.

## Data model

Additive migration on `STEP` (no other schema change):

- `feature_content` TEXT — registered copy for audit
- `feature_hash` TEXT — SHA-256 of the written content

## Drift detection

Hash comparison happens in `step_get_feature` and `step_run_tests`. Disk
always wins: execution proceeds, the response carries
`feature_drifted: true`, the audit log records `feature_drift`, the DB copy
is realigned. The human edits the spec freely; the agent always finds out.

## Error handling

- `step_set_feature` with malformed Gherkin → structured error, no disk write.
- `step_validate_feature` when behave is unavailable → explicit error
  ("behave not found"), never a false `syntax_ok`.
- `step_get_feature` with the file deleted from disk → `file_missing: true`
  plus the last DB copy as reference.
- Path safety: `filename` is sanitized and confined inside `features_dir`
  (no traversal, no absolute paths).

## Testing

TDD, same style as the BDD-gate work:

- storage: migration, content/hash persistence
- engine: set (write + hash + event), get (drift true/false, missing file),
  validate (parsing of real behave dry-run output, behave missing)
- app: endpoint contracts for the three tools
- e2e: set → validate → run → simulated manual edit → drift reported
