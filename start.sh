#!/usr/bin/env bash
# start.sh — BissetMCP unified launcher
# Usage: ./start.sh {start|stop|restart|status|logs} [service]
# service: all (default) | mcp-context | orchestrator | agent-<name>
#
# Reads config from .env in this directory (copy .env.example and fill in).

set -euo pipefail
ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
RUNDIR="$ROOT/.run"
LOGDIR="$ROOT/.logs"
mkdir -p "$RUNDIR" "$LOGDIR"

# ── load .env ─────────────────────────────────────────────────────────────────
if [[ -f "$ROOT/.env" ]]; then
  # export every non-comment, non-empty line
  set -a
  # shellcheck disable=SC1090
  source "$ROOT/.env"
  set +a
fi

OPENAI_API_KEY="${OPENAI_API_KEY:-}"
LLM_MODEL="${LLM_MODEL:-gpt-4o-mini}"
ORCHESTRATOR_PORT="${ORCHESTRATOR_PORT:-8080}"
PYTHON="$HOME/.pyenv/versions/bisset-mcp/bin/python"

# ── agent port map ────────────────────────────────────────────────────────────
declare -A AGENT_PORTS=(
  [sw-architect]=8101
  [product-owner]=8102
  [senior-developer]=8103
  [senior-frontend-developer]=8104
  [senior-database-engineer]=8105
  [senior-qa-engineer]=8106
  [ux-designer-senior]=8107
  [senior-product-manager]=8108
)

# ── helpers ───────────────────────────────────────────────────────────────────
pidfile() { echo "$RUNDIR/$1.pid"; }
logfile()  { echo "$LOGDIR/$1.log"; }

is_running() {
  local pf
  pf="$(pidfile "$1")"
  [[ -f "$pf" ]] && kill -0 "$(cat "$pf")" 2>/dev/null
}

stop_service() {
  local name="$1"
  local pf
  pf="$(pidfile "$name")"
  if is_running "$name"; then
    echo "  stopping $name (pid $(cat "$pf"))"
    kill "$(cat "$pf")" 2>/dev/null || true
    sleep 0.5
    rm -f "$pf"
  else
    echo "  $name not running"
  fi
}

# ── start functions ───────────────────────────────────────────────────────────
start_orchestrator() {
  local name="orchestrator"
  if is_running "$name"; then echo "  $name already running" ; return; fi
  local dir="$ROOT/orchestrator/orchestrator"

  # build AGENT_*_URL env vars pointing to localhost
  local agent_env=""
  for agent_name in "${!AGENT_PORTS[@]}"; do
    local port="${AGENT_PORTS[$agent_name]}"
    local key="AGENT_${agent_name^^}_URL"
    key="${key//-/_}"
    agent_env="$agent_env $key=http://localhost:$port/webhook"
  done

  echo "  installing deps for $name..."
  (cd "$dir" && "$PYTHON" -m pip install -q -r requirements.txt)
  echo "  starting $name → $(logfile "$name")"
  setsid env \
    MCP_URL="http://localhost:8080" \
    $agent_env \
    sh -c "cd '$dir' && '$PYTHON' app.py" > "$(logfile "$name")" 2>&1 < /dev/null &
  echo $! > "$(pidfile "$name")"
  echo "  $name started (pid $!)"
}

start_agent() {
  local agent_name="$1"           # e.g. sw-architect
  local service="agent-$agent_name"
  local port="${AGENT_PORTS[$agent_name]}"
  if is_running "$service"; then echo "  $service already running" ; return; fi
  local dir="$ROOT/orchestrator/agents/$service"
  if [[ ! -d "$dir" ]]; then echo "  WARNING: $dir not found, skipping"; return; fi

  echo "  installing deps for $service..."
  (cd "$dir" && "$PYTHON" -m pip install -q -r requirements.txt)
  echo "  starting $service on :$port → $(logfile "$service")"
  setsid env \
    OPENAI_API_KEY="$OPENAI_API_KEY" \
    LLM_MODEL="$LLM_MODEL" \
    PORT="$port" \
    sh -c "cd '$dir' && '$PYTHON' app.py" > "$(logfile "$service")" 2>&1 < /dev/null &
  echo $! > "$(pidfile "$service")"
  echo "  $service started (pid $!)"
}

# ── commands ──────────────────────────────────────────────────────────────────
cmd_start() {
  local target="${1:-all}"
  echo "==> start [$target]"
  if [[ "$target" == "all" ]]; then
    start_orchestrator
    for a in "${!AGENT_PORTS[@]}"; do start_agent "$a"; done
  elif [[ "$target" == "orchestrator" ]]; then
    start_orchestrator
  elif [[ "$target" == agent-* ]]; then
    local agent_name="${target#agent-}"
    start_agent "$agent_name"
  else
    echo "Unknown service: $target"; exit 1
  fi
}

cmd_stop() {
  local target="${1:-all}"
  echo "==> stop [$target]"
  if [[ "$target" == "all" ]]; then
    for svc in orchestrator; do stop_service "$svc"; done
    for a in "${!AGENT_PORTS[@]}"; do stop_service "agent-$a"; done
  elif [[ "$target" == "mcp-context" ]]; then
    stop_service "mcp-context"
  else
    stop_service "$target"
  fi
}

cmd_status() {
  echo "==> status"
  for svc in orchestrator; do
    local pf
    pf="$(pidfile "$svc")"
    if is_running "$svc"; then
      echo "  ✓ $svc  (pid $(cat "$pf"))"
    else
      echo "  ✗ $svc"
    fi
  done
  for a in "${!AGENT_PORTS[@]}"; do
    local svc="agent-$a"
    local pf
    pf="$(pidfile "$svc")"
    if is_running "$svc"; then
      echo "  ✓ $svc  (pid $(cat "$pf"))"
    else
      echo "  ✗ $svc"
    fi
  done
}

cmd_logs() {
  local target="${1:-}"
  if [[ -z "$target" ]]; then
    echo "Usage: $0 logs <service>"; exit 1
  fi
  local lf
  lf="$(logfile "$target")"
  if [[ -f "$lf" ]]; then
    tail -n 200 -f "$lf"
  else
    echo "No log file: $lf"; exit 1
  fi
}

cmd_restart() {
  local target="${1:-all}"
  cmd_stop "$target"
  sleep 1
  cmd_start "$target"
}

# ── dispatch ──────────────────────────────────────────────────────────────────
COMMAND="${1:-}"
EXTRA="${2:-all}"

case "$COMMAND" in
  start)   cmd_start   "$EXTRA" ;;
  stop)    cmd_stop    "$EXTRA" ;;
  restart) cmd_restart "$EXTRA" ;;
  status)  cmd_status ;;
  logs)    cmd_logs    "$EXTRA" ;;
  *)
    echo "Usage: $0 {start|stop|restart|status|logs} [service|all]"
    echo "Services: mcp-context  orchestrator  agent-<name>"
    echo "          all (default when omitted)"
    exit 2
    ;;
esac
