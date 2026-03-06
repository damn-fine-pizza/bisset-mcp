#!/usr/bin/env bash
# BissetMCP — database manager
# Usage: ./scripts/db.sh <command> [args]
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
REPO_ROOT="$(cd "$SCRIPT_DIR/.." && pwd)"

# ── Colours ──────────────────────────────────────────────────
RED='\033[0;31m'; GREEN='\033[0;32m'; YELLOW='\033[1;33m'
CYAN='\033[0;36m'; BOLD='\033[1m'; DIM='\033[2m'; RESET='\033[0m'

info()    { echo -e "${CYAN}[bisset-db]${RESET} $*"; }
success() { echo -e "${GREEN}[bisset-db]${RESET} $*"; }
warn()    { echo -e "${YELLOW}[bisset-db]${RESET} $*"; }
error()   { echo -e "${RED}[bisset-db] ERROR:${RESET} $*" >&2; }

# ── Load .env for DATABASE_PATH ──────────────────────────────
if [[ -f "$REPO_ROOT/.env" ]]; then
    set -o allexport
    # shellcheck disable=SC1090
    source <(grep -v '^#' "$REPO_ROOT/.env" | grep -v '^[[:space:]]*$')
    set +o allexport
fi

DB="${DATABASE_PATH:-$REPO_ROOT/orchestrator/workflow_server/workflow.db}"

if [[ ! -f "$DB" ]]; then
    error "Database not found: $DB"
    echo "  Start the workflow server first, or set DATABASE_PATH."
    exit 1
fi

# ── Help ──────────────────────────────────────────────────────
usage() {
    echo -e "${BOLD}Usage:${RESET} ./scripts/db.sh <command> [args]"
    echo ""
    echo -e "${BOLD}Commands:${RESET}"
    echo "  projects                 List all projects"
    echo "  sessions [project_id]    List sessions (optionally filter by project)"
    echo "  steps <session_id>       List steps for a session"
    echo "  events <session_id>      List events for a session"
    echo "  runs <step_id>           List test runs for a step"
    echo "  detail <session_id>      Full session detail (steps + latest test run)"
    echo ""
    echo "  delete-session <id>      Delete a session and all its data"
    echo "  delete-project <id>      Delete a project and all its sessions"
    echo "  reset                    Delete ALL data (asks for confirmation)"
    echo ""
    echo "  sql '<query>'            Run arbitrary SQL (read-only)"
    echo "  shell                    Open interactive sqlite3 shell"
    echo ""
    echo -e "${BOLD}Database:${RESET} $DB"
}

CMD="${1:-}"
[[ -z "$CMD" || "$CMD" == "--help" || "$CMD" == "-h" ]] && usage && exit 0

# ── Helper: run sqlite3 ──────────────────────────────────────
run_sql() {
    sqlite3 -header -column "$DB" "$1"
}

run_sql_noheader() {
    sqlite3 "$DB" "$1"
}

# ── projects ──────────────────────────────────────────────────
if [[ "$CMD" == "projects" ]]; then
    info "Projects:"
    run_sql "SELECT id, name, path, adapter, datetime(created_at, 'unixepoch', 'localtime') AS created FROM projects ORDER BY created_at;"
    exit 0
fi

# ── sessions ──────────────────────────────────────────────────
if [[ "$CMD" == "sessions" ]]; then
    FILTER="${2:-}"
    if [[ -n "$FILTER" ]]; then
        info "Sessions for project $FILTER:"
        run_sql "SELECT s.id, s.workflow_type, s.status, p.name AS project, datetime(s.created_at, 'unixepoch', 'localtime') AS created FROM sessions s JOIN projects p ON s.project_id = p.id WHERE s.project_id = '$FILTER' ORDER BY s.created_at;"
    else
        info "All sessions:"
        run_sql "SELECT s.id, s.workflow_type, s.status, p.name AS project, datetime(s.created_at, 'unixepoch', 'localtime') AS created FROM sessions s JOIN projects p ON s.project_id = p.id ORDER BY s.created_at;"
    fi
    exit 0
fi

# ── steps ─────────────────────────────────────────────────────
if [[ "$CMD" == "steps" ]]; then
    SID="${2:?session_id required}"
    info "Steps for session $SID:"
    run_sql "SELECT id, \"order\", title, status, gate, retries, current_coverage FROM steps WHERE session_id = '$SID' ORDER BY \"order\";"
    exit 0
fi

# ── events ────────────────────────────────────────────────────
if [[ "$CMD" == "events" ]]; then
    SID="${2:?session_id required}"
    LIMIT="${3:-50}"
    info "Events for session $SID (last $LIMIT):"
    run_sql "SELECT id, event_type, step_id, datetime(timestamp, 'unixepoch', 'localtime') AS at FROM events WHERE session_id = '$SID' ORDER BY timestamp DESC LIMIT $LIMIT;"
    exit 0
fi

# ── runs ──────────────────────────────────────────────────────
if [[ "$CMD" == "runs" ]]; then
    STEP_ID="${2:?step_id required}"
    info "Test runs for step $STEP_ID:"
    run_sql "SELECT id, passed, failed, coverage, datetime(run_at, 'unixepoch', 'localtime') AS at FROM test_runs WHERE step_id = '$STEP_ID' ORDER BY run_at DESC;"
    exit 0
fi

# ── detail ────────────────────────────────────────────────────
if [[ "$CMD" == "detail" ]]; then
    SID="${2:?session_id required}"
    info "Session detail for $SID:"
    echo ""
    run_sql "SELECT s.id, s.workflow_type, s.status, p.name AS project, p.path AS project_path FROM sessions s JOIN projects p ON s.project_id = p.id WHERE s.id = '$SID';"
    echo ""
    info "Steps:"
    run_sql "SELECT st.id, st.\"order\", st.title, st.status, st.gate, st.retries, st.current_coverage, tr.passed AS last_passed, tr.failed AS last_failed FROM steps st LEFT JOIN (SELECT step_id, passed, failed, MAX(run_at) FROM test_runs GROUP BY step_id) tr ON tr.step_id = st.id WHERE st.session_id = '$SID' ORDER BY st.\"order\";"
    exit 0
fi

# ── delete-session ────────────────────────────────────────────
if [[ "$CMD" == "delete-session" ]]; then
    SID="${2:?session_id required}"
    # Show what will be deleted
    COUNT_STEPS=$(run_sql_noheader "SELECT COUNT(*) FROM steps WHERE session_id = '$SID';")
    COUNT_EVENTS=$(run_sql_noheader "SELECT COUNT(*) FROM events WHERE session_id = '$SID';")
    COUNT_RUNS=$(run_sql_noheader "SELECT COUNT(*) FROM test_runs WHERE session_id = '$SID';")
    warn "Will delete session $SID: $COUNT_STEPS steps, $COUNT_RUNS test runs, $COUNT_EVENTS events"
    read -rp "Confirm? [y/N] " REPLY
    if [[ "$REPLY" =~ ^[Yy]$ ]]; then
        sqlite3 "$DB" "
            DELETE FROM events WHERE session_id = '$SID';
            DELETE FROM test_runs WHERE session_id = '$SID';
            DELETE FROM steps WHERE session_id = '$SID';
            DELETE FROM sessions WHERE id = '$SID';
        "
        success "Deleted session $SID"
    else
        info "Cancelled"
    fi
    exit 0
fi

# ── delete-project ────────────────────────────────────────────
if [[ "$CMD" == "delete-project" ]]; then
    PID="${2:?project_id required}"
    PROJ_NAME=$(run_sql_noheader "SELECT name FROM projects WHERE id = '$PID';")
    if [[ -z "$PROJ_NAME" ]]; then
        error "Project $PID not found"
        exit 1
    fi
    COUNT_SESSIONS=$(run_sql_noheader "SELECT COUNT(*) FROM sessions WHERE project_id = '$PID';")
    warn "Will delete project '$PROJ_NAME' ($PID) and $COUNT_SESSIONS session(s) with all their data"
    read -rp "Confirm? [y/N] " REPLY
    if [[ "$REPLY" =~ ^[Yy]$ ]]; then
        sqlite3 "$DB" "
            DELETE FROM events WHERE session_id IN (SELECT id FROM sessions WHERE project_id = '$PID');
            DELETE FROM test_runs WHERE session_id IN (SELECT id FROM sessions WHERE project_id = '$PID');
            DELETE FROM steps WHERE session_id IN (SELECT id FROM sessions WHERE project_id = '$PID');
            DELETE FROM sessions WHERE project_id = '$PID';
            DELETE FROM projects WHERE id = '$PID';
        "
        success "Deleted project '$PROJ_NAME' and all its data"
    else
        info "Cancelled"
    fi
    exit 0
fi

# ── reset ─────────────────────────────────────────────────────
if [[ "$CMD" == "reset" ]]; then
    warn "This will DELETE ALL DATA in $DB"
    read -rp "Type 'yes' to confirm: " REPLY
    if [[ "$REPLY" == "yes" ]]; then
        sqlite3 "$DB" "
            DELETE FROM events;
            DELETE FROM test_runs;
            DELETE FROM steps;
            DELETE FROM sessions;
            DELETE FROM projects;
        "
        success "All data deleted"
    else
        info "Cancelled"
    fi
    exit 0
fi

# ── sql ───────────────────────────────────────────────────────
if [[ "$CMD" == "sql" ]]; then
    QUERY="${2:?SQL query required}"
    run_sql "$QUERY"
    exit 0
fi

# ── shell ─────────────────────────────────────────────────────
if [[ "$CMD" == "shell" ]]; then
    info "Opening sqlite3 shell for $DB"
    exec sqlite3 -header -column "$DB"
fi

error "Unknown command: $CMD"
echo ""
usage
exit 1
