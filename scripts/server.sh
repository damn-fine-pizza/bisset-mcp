#!/usr/bin/env bash
# BissetMCP — server management script
set -euo pipefail

# ── Locate repo root ─────────────────────────────────────────
SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
REPO_ROOT="$(cd "$SCRIPT_DIR/.." && pwd)"

# ── Colours ──────────────────────────────────────────────────
RED='\033[0;31m'; GREEN='\033[0;32m'; YELLOW='\033[1;33m'
CYAN='\033[0;36m'; BOLD='\033[1m'; DIM='\033[2m'; RESET='\033[0m'

info()    { echo -e "${CYAN}[bisset]${RESET} $*"; }
success() { echo -e "${GREEN}[bisset]${RESET} $*"; }
warn()    { echo -e "${YELLOW}[bisset]${RESET} $*"; }
error()   { echo -e "${RED}[bisset] ERROR:${RESET} $*" >&2; }

# ── Paths ─────────────────────────────────────────────────────
LOG_DIR="$REPO_ROOT/logs"
mkdir -p "$LOG_DIR"
WORKFLOW_PID="$LOG_DIR/workflow-server.pid"
LOG_FILE="$LOG_DIR/workflow-server.log"

# ── Help ──────────────────────────────────────────────────────
usage() {
    echo -e "${BOLD}Usage:${RESET} ./scripts/server.sh <command>"
    echo ""
    echo -e "${BOLD}Commands:${RESET}"
    echo "  start        Start the workflow_server (with hot reload)"
    echo "  start mcp    Start + print CLI registration commands"
    echo "  stop         Stop the running workflow_server"
    echo "  logs         Tail workflow_server logs"
    echo "  logs mcp     Tail MCP server logs"
    echo "  --help       Show this help"
    echo ""
    echo -e "${BOLD}Examples:${RESET}"
    echo "  ./scripts/server.sh start"
    echo "  ./scripts/server.sh start mcp"
    echo "  ./scripts/server.sh logs"
    echo "  ./scripts/server.sh logs mcp"
    echo "  ./scripts/server.sh stop"
}

CMD="${1:-}"
[[ -z "$CMD" || "$CMD" == "--help" ]] && usage && exit 0

# ── logs ──────────────────────────────────────────────────────
if [[ "$CMD" == "logs" ]]; then
    if [[ "${2:-}" == "mcp" ]]; then
        MCP_LOG="$LOG_DIR/mcp-server.log"
        if [[ ! -f "$MCP_LOG" ]]; then
            warn "MCP log not found: $MCP_LOG (MCP server never started?)"
            exit 1
        fi
        exec tail -f "$MCP_LOG"
    fi
    if [[ ! -f "$LOG_FILE" ]]; then
        warn "Log file not found: $LOG_FILE (server never started?)"
        exit 1
    fi
    exec tail -f "$LOG_FILE"
fi

# ── stop ──────────────────────────────────────────────────────
if [[ "$CMD" == "stop" ]]; then
    if [[ -f "$WORKFLOW_PID" ]]; then
        PID=$(cat "$WORKFLOW_PID")
        if kill "$PID" 2>/dev/null; then
            success "Stopped workflow_server (PID $PID)"
        else
            warn "workflow_server PID $PID not found (already stopped?)"
        fi
        rm -f "$WORKFLOW_PID"
    else
        # fallback: find uvicorn process by port
        PID=$(ps aux | grep "uvicorn orchestrator.workflow_server" | grep -v grep | awk '{print $2}' | head -1)
        if [[ -n "$PID" ]]; then
            kill "$PID" && success "Stopped workflow_server (PID $PID, found via ps)"
        else
            warn "No running workflow_server found"
        fi
    fi
    exit 0
fi

# ── start ─────────────────────────────────────────────────────
if [[ "$CMD" != "start" ]]; then
    error "Unknown command: $CMD"
    echo ""
    usage
    exit 1
fi

WITH_MCP=false
[[ "${2:-}" == "mcp" ]] && WITH_MCP=true

# ── Check Python ─────────────────────────────────────────────
PYTHON=$(command -v python3 || command -v python || true)
if [[ -z "$PYTHON" ]]; then
    error "python3 not found. Install Python 3.10+ and try again."
    exit 1
fi

PYVER=$("$PYTHON" -c 'import sys; print(f"{sys.version_info.major}.{sys.version_info.minor}")')
info "Python $PYVER at $PYTHON"

# ── Check / activate virtualenv ──────────────────────────────
VENV_DIR="$REPO_ROOT/.venv"
if [[ -d "$VENV_DIR" ]]; then
    # shellcheck disable=SC1091
    source "$VENV_DIR/bin/activate"
    info "Activated virtualenv: $VENV_DIR"
else
    warn "No .venv found. Creating one now..."
    "$PYTHON" -m venv "$VENV_DIR"
    # shellcheck disable=SC1091
    source "$VENV_DIR/bin/activate"
    success "Created virtualenv: $VENV_DIR"
fi

# ── Install dependencies ─────────────────────────────────────
REQ="$REPO_ROOT/requirements.txt"
info "Checking Python dependencies..."
pip install --quiet fastapi uvicorn httpx pydantic 2>/dev/null || true
if [[ -f "$REQ" ]]; then
    pip install --quiet -r "$REQ" 2>/dev/null || true
fi

# ── Load .env ────────────────────────────────────────────────
ENV_FILE="$REPO_ROOT/.env"
ENV_EXAMPLE="$REPO_ROOT/.env.example"

if [[ ! -f "$ENV_FILE" ]]; then
    if [[ -f "$ENV_EXAMPLE" ]]; then
        warn ".env not found — copying from .env.example"
        cp "$ENV_EXAMPLE" "$ENV_FILE"
        warn "Edit $ENV_FILE before starting."
    else
        warn "No .env file found. Using defaults."
    fi
fi

if [[ -f "$ENV_FILE" ]]; then
    set -o allexport
    # shellcheck disable=SC1090
    source <(grep -v '^#' "$ENV_FILE" | grep -v '^[[:space:]]*$')
    set +o allexport
    info "Loaded environment from $ENV_FILE"
fi

PORT="${WORKFLOW_SERVER_PORT:-8765}"
DB_PATH="${DATABASE_PATH:-$REPO_ROOT/orchestrator/workflow_server/workflow.db}"
mkdir -p "$(dirname "$DB_PATH")"

# ── Kill any leftover server ──────────────────────────────────
if [[ -f "$WORKFLOW_PID" ]]; then
    OLD_PID=$(cat "$WORKFLOW_PID")
    if kill -0 "$OLD_PID" 2>/dev/null; then
        warn "Stopping existing workflow_server (PID $OLD_PID)..."
        kill "$OLD_PID" && sleep 1
    fi
    rm -f "$WORKFLOW_PID"
fi

# ── Start workflow_server ─────────────────────────────────────
info "Starting workflow_server on port $PORT (hot reload enabled)..."

cd "$REPO_ROOT"
DATABASE_PATH="$DB_PATH" \
FORCE_COLOR=1 \
nohup "$PYTHON" -m uvicorn orchestrator.workflow_server.app:app \
    --host 127.0.0.1 \
    --port "$PORT" \
    --reload \
    --reload-dir "$REPO_ROOT/orchestrator" \
    --log-level info \
    --use-colors \
    > "$LOG_FILE" 2>&1 &

echo $! > "$WORKFLOW_PID"
WF_PID=$(cat "$WORKFLOW_PID")
info "workflow_server PID: $WF_PID  |  log: ./logs/workflow-server.log"

# ── Wait for health ───────────────────────────────────────────
info "Waiting for workflow_server to be ready..."
for i in $(seq 1 20); do
    if curl -sf "http://127.0.0.1:$PORT/health" > /dev/null 2>&1; then
        success "workflow_server is healthy  (http://127.0.0.1:$PORT)"
        break
    fi
    sleep 0.5
    if [[ $i -eq 20 ]]; then
        error "workflow_server did not start within 10s."
        error "Check logs: ./logs/workflow-server.log"
        exit 1
    fi
done

# ── Print MCP registration commands ───────────────────────────
if $WITH_MCP; then
    VENV_PY="$VENV_DIR/bin/python3"
    echo ""
    echo -e "${BOLD}══════════════════════════════════════════════════════${RESET}"
    echo -e "${BOLD}  Register bisset — Claude CLI (run once):${RESET}"
    echo -e "${BOLD}══════════════════════════════════════════════════════${RESET}"
    echo ""
    echo -e "${CYAN}claude mcp add bisset \\"
    echo -e "  -e WORKFLOW_BACKEND_URL=http://127.0.0.1:${PORT} \\"
    echo -e "  -e PYTHONPATH=${REPO_ROOT} \\"
    echo -e "  -- ${VENV_PY} -m orchestrator.mcp_server${RESET}"
    echo ""
    echo -e "${BOLD}══════════════════════════════════════════════════════${RESET}"
    echo -e "${BOLD}  Register bisset — Copilot CLI / VS Code:${RESET}"
    echo -e "${BOLD}══════════════════════════════════════════════════════${RESET}"
    echo ""
    echo -e "${DIM}Add to ~/.config/github-copilot/mcp.json (or VS Code MCP config):${RESET}"
    echo ""
    echo -e "${CYAN}{"
    echo -e "  \"servers\": {"
    echo -e "    \"bisset\": {"
    echo -e "      \"type\": \"stdio\","
    echo -e "      \"command\": \"${VENV_PY}\","
    echo -e "      \"args\": [\"-m\", \"orchestrator.mcp_server\"],"
    echo -e "      \"env\": {"
    echo -e "        \"PYTHONPATH\": \"${REPO_ROOT}\","
    echo -e "        \"WORKFLOW_BACKEND_URL\": \"http://127.0.0.1:${PORT}\""
    echo -e "      }"
    echo -e "    }"
    echo -e "  }"
    echo -e "}${RESET}"
    echo ""
fi

success "Done. workflow_server is running (hot reload on)."
echo -e "  Stop with:  ${BOLD}./scripts/server.sh stop${RESET}"
echo -e "  Logs at:    ${BOLD}./logs/workflow-server.log${RESET}"
