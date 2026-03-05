#!/usr/bin/env bash
# start.sh — BissetMCP unified launcher
# Usage: ./start.sh {start|stop|restart|status|logs} [service]
# service: all (default) | workflow-server
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

PYTHON="$HOME/.pyenv/versions/bisset-mcp/bin/python"

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
start_workflow_server() {
  local name="workflow-server"
  if is_running "$name"; then echo "  $name already running" ; return; fi
  local dir="$ROOT/orchestrator"

  echo "  installing deps for $name..."
  (cd "$dir" && "$PYTHON" -m pip install -q -r workflow_server/requirements.txt)
  echo "  starting $name on :8765 → $(logfile "$name")"
  setsid env \
    sh -c "cd '$dir' && '$PYTHON' -m orchestrator.workflow_server" > "$(logfile "$name")" 2>&1 < /dev/null &
  echo $! > "$(pidfile "$name")"
  echo "  $name started (pid $!)"
}

start_mcp_server() {
  local name="mcp-server"
  if is_running "$name"; then echo "  $name already running" ; return; fi
  local dir="$ROOT/orchestrator"

  echo "  installing deps for $name..."
  (cd "$dir" && "$PYTHON" -m pip install -q -r mcp_server/requirements.txt)
  echo "  starting $name on stdio → $(logfile "$name")"
  setsid env \
    sh -c "cd '$dir' && '$PYTHON' -m orchestrator.mcp_server" > "$(logfile "$name")" 2>&1 < /dev/null &
  echo $! > "$(pidfile "$name")"
  echo "  $name started (pid $!)"
}

# ── commands ──────────────────────────────────────────────────────────────────
cmd_start() {
  local target="${1:-all}"
  echo "==> start [$target]"
  if [[ "$target" == "all" ]]; then
    start_workflow_server
    start_mcp_server
  elif [[ "$target" == "workflow-server" ]]; then
    start_workflow_server
  elif [[ "$target" == "mcp-server" ]]; then
    start_mcp_server
  else
    echo "Unknown service: $target"; exit 1
  fi
}

cmd_stop() {
  local target="${1:-all}"
  echo "==> stop [$target]"
  if [[ "$target" == "all" ]]; then
    stop_service "workflow-server"
    stop_service "mcp-server"
  else
    stop_service "$target"
  fi
}

cmd_status() {
  echo "==> status"
  for svc in workflow-server mcp-server; do
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
    echo "Services: workflow-server  mcp-server"
    echo "          all (default when omitted)"
    exit 2
    ;;
esac
