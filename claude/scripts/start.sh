#!/usr/bin/env bash
# ============================================================
# BissetMCP – Claude Edition — start script
#
# Usage:
#   ./claude/scripts/start.sh              # start workflow_server only
#   ./claude/scripts/start.sh --with-mcp  # also print Claude Desktop config
#   ./claude/scripts/start.sh --stop      # stop running servers
#
# The script must be run from the repository root, or from inside claude/.
# ============================================================
set -euo pipefail

# ── Locate repo root ─────────────────────────────────────────
SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
REPO_ROOT="$(cd "$SCRIPT_DIR/../.." && pwd)"
CLAUDE_DIR="$REPO_ROOT/claude"

# ── Colours ──────────────────────────────────────────────────
RED='\033[0;31m'; GREEN='\033[0;32m'; YELLOW='\033[1;33m'
CYAN='\033[0;36m'; BOLD='\033[1m'; RESET='\033[0m'

info()    { echo -e "${CYAN}[bisset]${RESET} $*"; }
success() { echo -e "${GREEN}[bisset]${RESET} $*"; }
warn()    { echo -e "${YELLOW}[bisset]${RESET} $*"; }
error()   { echo -e "${RED}[bisset] ERROR:${RESET} $*" >&2; }

# ── PID files ────────────────────────────────────────────────
LOG_DIR="$CLAUDE_DIR/logs"
mkdir -p "$LOG_DIR"
RUN_DIR="$CLAUDE_DIR/logs"
mkdir -p "$RUN_DIR"
WORKFLOW_PID="$RUN_DIR/workflow-server.pid"

# ── Stop mode ────────────────────────────────────────────────
if [[ "${1:-}" == "--stop" ]]; then
    if [[ -f "$WORKFLOW_PID" ]]; then
        PID=$(cat "$WORKFLOW_PID")
        if kill "$PID" 2>/dev/null; then
            success "Stopped workflow_server (PID $PID)"
        else
            warn "workflow_server PID $PID not found (already stopped?)"
        fi
        rm -f "$WORKFLOW_PID"
    else
        warn "No PID file found — workflow_server may not be running"
    fi
    exit 0
fi

WITH_MCP=false
[[ "${1:-}" == "--with-mcp" ]] && WITH_MCP=true

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
REQ="$CLAUDE_DIR/requirements.txt"
WF_REQ="$CLAUDE_DIR/orchestrator/workflow_server/../../../claude/requirements.txt"

info "Checking Python dependencies..."
pip install --quiet fastapi uvicorn httpx pydantic 2>/dev/null || true
if [[ -f "$REQ" ]]; then
    pip install --quiet -r "$REQ" 2>/dev/null || true
fi

# ── Load .env ────────────────────────────────────────────────
ENV_FILE="$CLAUDE_DIR/.env"
ENV_EXAMPLE="$CLAUDE_DIR/.env.example"

if [[ ! -f "$ENV_FILE" ]]; then
    if [[ -f "$ENV_EXAMPLE" ]]; then
        warn ".env not found — copying from .env.example"
        cp "$ENV_EXAMPLE" "$ENV_FILE"
        warn "Edit $ENV_FILE and set CLAUDE_API_KEY before using live Claude API."
    else
        warn "No .env file found. Using defaults."
    fi
fi

if [[ -f "$ENV_FILE" ]]; then
    # Export non-comment, non-empty lines
    set -o allexport
    # shellcheck disable=SC1090
    source <(grep -v '^#' "$ENV_FILE" | grep -v '^[[:space:]]*$')
    set +o allexport
    info "Loaded environment from $ENV_FILE"
fi

PORT="${WORKFLOW_SERVER_PORT:-8765}"
DB_PATH="${DATABASE_PATH:-$CLAUDE_DIR/orchestrator/workflow_server/workflow.db}"
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
info "Starting workflow_server on port $PORT..."

cd "$CLAUDE_DIR"
WORKFLOW_PRETTY_JSON_LOGS="${WORKFLOW_PRETTY_JSON_LOGS:-1}" \
DATABASE_PATH="$DB_PATH" \
nohup "$PYTHON" -m uvicorn orchestrator.workflow_server.app:app \
    --host 127.0.0.1 \
    --port "$PORT" \
    --log-level warning \
    > "$LOG_DIR/workflow-server.log" 2>&1 &

echo $! > "$WORKFLOW_PID"
WF_PID=$(cat "$WORKFLOW_PID")
info "workflow_server PID: $WF_PID  |  log: ./claude/logs/workflow-server.log"


# ── Wait for health ───────────────────────────────────────────
info "Waiting for workflow_server to be ready..."
for i in $(seq 1 20); do
    if curl -sf "http://127.0.0.1:$PORT/health" > /dev/null 2>&1; then
        success "workflow_server is healthy ✓  (http://127.0.0.1:$PORT)"
        break
    fi
    sleep 0.5
    if [[ $i -eq 20 ]]; then
        error "workflow_server did not start within 10s."
        error "Check logs: ./claude/logs/workflow-server.log"
        exit 1
    fi
done

# ── Print Claude Desktop config ───────────────────────────────
if $WITH_MCP; then
    MCP_CMD="$PYTHON"
    MCP_ARGS="-m orchestrator.mcp_server"
    MCP_CWD="$CLAUDE_DIR"

    echo ""
    echo -e "${BOLD}══════════════════════════════════════════════════════${RESET}"
    echo -e "${BOLD}  Claude Desktop  —  MCP server configuration${RESET}"
    echo -e "${BOLD}══════════════════════════════════════════════════════${RESET}"
    echo ""
    echo "Add the following block to your claude_desktop_config.json"
    echo "(usually at ~/Library/Application Support/Claude/claude_desktop_config.json"
    echo " or %APPDATA%\\Claude\\claude_desktop_config.json on Windows):"
    echo ""
    echo -e "${CYAN}"
    cat <<EOF
{
  "mcpServers": {
    "bisset": {
      "command": "$MCP_CMD",
      "args": ["$MCP_ARGS"],
      "cwd": "$MCP_CWD",
      "env": {
        "WORKFLOW_BACKEND_URL": "http://127.0.0.1:$PORT",
        "DATABASE_PATH": "$DB_PATH"
      }
    }
  }
}
EOF
    echo -e "${RESET}"
    echo -e "${YELLOW}Note:${RESET} the workflow_server must be running before Claude Desktop starts the MCP server."
    echo -e "      Run ${BOLD}./claude/scripts/start.sh${RESET} on every login, or add it to your system startup."
    echo ""
fi

success "Done. workflow_server is running."
echo -e "  Stop with:  ${BOLD}./claude/scripts/start.sh --stop${RESET}"
echo -e "  Logs at:    ${BOLD}./claude/logs/workflow-server.log${RESET}"
