#!/usr/bin/env bash
# demo_bdd_gate.sh — deterministic, reproducible demo of the Bisset BDD gate.
#
# Thesis: Bisset is not a test runner, it is a GATEKEEPER. The demo proves it
# by attempting to accept a step while its Gherkin scenarios are still red and
# asserting that Bisset blocks the acceptance.
#
# Flow:
#   1. start an isolated workflow server (own port, own temp SQLite DB)
#   2. create project + session + step with Gherkin acceptance criteria
#   3. run behave            -> RED (subtract() is buggy)
#   4. attempt to accept     -> Bisset must BLOCK (action != advance)
#   5. apply the fix
#   6. run behave            -> GREEN (scenario coverage 100%)
#   7. accept                -> advance, session completed
#
# Exit codes:
#   0  demo passed end to end
#   1  environment / setup failure
#   2  server did not become healthy
#   3  expected RED test run was not red
#   4  GATE FAILURE: Bisset accepted a step with red tests
#   5  test run still red after applying the fix
#   6  final acceptance did not advance / session not completed
set -euo pipefail

REPO_ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
VENV_PY="$REPO_ROOT/.venv/bin/python3"
VENV_BEHAVE="$REPO_ROOT/.venv/bin/behave"

# ── Pretty output ─────────────────────────────────────────────────────────────
C_BLUE=$'\033[1;34m'; C_GREEN=$'\033[1;32m'; C_RED=$'\033[1;31m'; C_OFF=$'\033[0m'
phase() { printf '\n%s[%s]%s %s\n' "$C_BLUE" "$1" "$C_OFF" "$2"; }
ok()    { printf '%s  ✔ %s%s\n' "$C_GREEN" "$1" "$C_OFF"; }
die()   { printf '%s  ✘ %s%s\n' "$C_RED" "$2" "$C_OFF" >&2; exit "$1"; }

# ── Environment checks ────────────────────────────────────────────────────────
[ -x "$VENV_PY" ]     || die 1 "No .venv found. Run: python3 -m venv .venv && pip install -r requirements.txt -r requirements-dev.txt"
[ -x "$VENV_BEHAVE" ] || die 1 "behave not installed in .venv. Run: pip install -r requirements-dev.txt"

# ── Isolated workspace + server lifecycle ─────────────────────────────────────
WORKDIR="$(mktemp -d /tmp/bisset-demo.XXXXXX)"
SERVER_PID=""
cleanup() {
    status=$?
    if [ -n "$SERVER_PID" ] && kill -0 "$SERVER_PID" 2>/dev/null; then
        kill "$SERVER_PID" 2>/dev/null || true
        wait "$SERVER_PID" 2>/dev/null || true
    fi
    if [ "$status" -ne 0 ] && [ -f "$WORKDIR/server.log" ]; then
        printf '%s--- server log tail ---%s\n' "$C_RED" "$C_OFF" >&2
        tail -20 "$WORKDIR/server.log" >&2 || true
    fi
    rm -rf "$WORKDIR"
}
trap cleanup EXIT

phase "1/8" "Starting isolated workflow server"
cp -r "$REPO_ROOT/examples/demo/project/." "$WORKDIR/project/"

# Pick a free port (handles "port already in use" deterministically)
PORT="$("$VENV_PY" -c 'import socket; s=socket.socket(); s.bind(("127.0.0.1",0)); print(s.getsockname()[1]); s.close()')"
BASE="http://127.0.0.1:$PORT"

DATABASE_PATH="$WORKDIR/bisset.db" PYTHONPATH="$REPO_ROOT" \
    "$VENV_PY" -m uvicorn orchestrator.workflow_server.app:app \
    --host 127.0.0.1 --port "$PORT" --log-level warning \
    > "$WORKDIR/server.log" 2>&1 &
SERVER_PID=$!

# Health-check loop (no fixed sleep)
for i in $(seq 1 50); do
    if curl -sf "$BASE/health" > /dev/null 2>&1; then break; fi
    kill -0 "$SERVER_PID" 2>/dev/null || die 2 "Server process died during startup"
    sleep 0.2
    [ "$i" -eq 50 ] && die 2 "Server did not become healthy on $BASE within 10s"
done
ok "Server healthy on $BASE (DB: \$WORKDIR/bisset.db)"

# ── HTTP helpers ──────────────────────────────────────────────────────────────
# All responses are wrapped: {"content":[{"text":"<inner json>"}], ...}
# jget RESPONSE FIELD  -> extract FIELD from the inner JSON
jget() { "$VENV_PY" -c '
import json, sys
resp = json.loads(sys.argv[1])
if resp.get("is_error"):
    sys.exit(f"backend error: {resp}")
inner = json.loads(resp["content"][0]["text"])
val = inner
for part in sys.argv[2].split("."):
    val = val[part]
print(json.dumps(val) if isinstance(val, (dict, list)) else val)
' "$1" "$2"; }

post() { curl -sf -X POST "$BASE/$1" -H 'Content-Type: application/json' -d "$2"; }
get()  { curl -sf "$BASE/$1"; }

phase "2/8" "Creating project, session, and gated step"
RESP="$(post project_create "{\"name\":\"bdd-gate-demo\",\"path\":\"$WORKDIR/project\",\"test_runner\":\"$VENV_BEHAVE\",\"test_args\":\"--format json --no-snippets\",\"adapter\":\"behave\"}")"
PROJECT_ID="$(jget "$RESP" project_id)"
RESP="$(post session_start "{\"project_id\":\"$PROJECT_ID\",\"workflow_type\":\"new_feature\"}")"
SESSION_ID="$(jget "$RESP" session_id)"
RESP="$(post step_add "{\"session_id\":\"$SESSION_ID\",\"title\":\"Implement calculator\",\"description\":\"add() and subtract() must satisfy calculator.feature\",\"order\":1,\"feature_path\":\"features/calculator.feature\",\"gate\":\"tests_only\"}")"
STEP_ID="$(jget "$RESP" step_id)"
ok "project=$PROJECT_ID session=$SESSION_ID step=$STEP_ID (engine default rules in effect)"

phase "3/8" "Running Gherkin acceptance tests (expecting RED: subtract() is buggy)"
RESP="$(post step_run_tests "{\"step_id\":\"$STEP_ID\",\"session_id\":\"$SESSION_ID\"}")"
PASSED="$(jget "$RESP" passed)"; FAILED="$(jget "$RESP" failed)"; COV="$(jget "$RESP" coverage)"
[ "$FAILED" -gt 0 ] || die 3 "Expected red tests, got passed=$PASSED failed=$FAILED"
ok "RED as expected: $PASSED passed, $FAILED failed, scenario coverage $COV%"

phase "4/8" "Attempting to accept the step with RED tests — Bisset must block"
RESP="$(post step_complete "{\"step_id\":\"$STEP_ID\",\"session_id\":\"$SESSION_ID\"}")"
ACTION="$(jget "$RESP" action)"
if [ "$ACTION" = "advance" ]; then
    die 4 "GATE FAILURE: Bisset accepted a step with red tests (action=advance)"
fi
RESP="$(get "step_list?session_id=$SESSION_ID")"
STATUS="$("$VENV_PY" -c '
import json, sys
inner = json.loads(json.loads(sys.argv[1])["content"][0]["text"])
print(inner["steps"][0]["status"])
' "$RESP")"
[ "$STATUS" != "passed" ] || die 4 "GATE FAILURE: step marked passed despite red tests"
ok "Acceptance BLOCKED: action=$ACTION, step status=$STATUS"

phase "5/8" "Applying the fix (subtract operands corrected)"
cp "$REPO_ROOT/examples/demo/fix/calc.py" "$WORKDIR/project/calc.py"
ok "fix applied to calc.py"

phase "6/8" "Re-running Gherkin acceptance tests (expecting GREEN)"
RESP="$(post step_run_tests "{\"step_id\":\"$STEP_ID\",\"session_id\":\"$SESSION_ID\"}")"
PASSED="$(jget "$RESP" passed)"; FAILED="$(jget "$RESP" failed)"; COV="$(jget "$RESP" coverage)"
[ "$FAILED" -eq 0 ] && [ "$PASSED" -gt 0 ] || die 5 "Tests still red after fix: passed=$PASSED failed=$FAILED"
ok "GREEN: $PASSED passed, $FAILED failed, scenario coverage $COV%"

phase "7/8" "Accepting the step with GREEN tests — Bisset must advance"
RESP="$(post step_complete "{\"step_id\":\"$STEP_ID\",\"session_id\":\"$SESSION_ID\"}")"
ACTION="$(jget "$RESP" action)"
[ "$ACTION" = "advance" ] || die 6 "Expected advance with green tests, got action=$ACTION"
ok "Acceptance GRANTED: action=advance"

phase "8/8" "Final report"
RESP="$(get "pipeline_report?session_id=$SESSION_ID")"
SESSION_STATUS="$(jget "$RESP" session.status)"
COMPLETED="$(jget "$RESP" completed_steps)"; TOTAL="$(jget "$RESP" total_steps)"
[ "$SESSION_STATUS" = "completed" ] || die 6 "Session not completed (status=$SESSION_STATUS)"
ok "Session $SESSION_STATUS — steps passed: $COMPLETED/$TOTAL"

printf '\n%sDEMO PASSED%s — red tests blocked acceptance, the fix unblocked it.\n' "$C_GREEN" "$C_OFF"
