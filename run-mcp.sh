#!/usr/bin/env bash
# Launch the Bisset MCP STDIO server using the project-local virtualenv.
# Safe to invoke from any directory (e.g. as an MCP client command).
set -euo pipefail
REPO_ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
cd "$REPO_ROOT"
exec "$REPO_ROOT/.venv/bin/python3" -m orchestrator.mcp_server "$@"
