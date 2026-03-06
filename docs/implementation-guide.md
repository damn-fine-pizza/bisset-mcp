# BissetMCP Implementation Guide — Claude Edition

End-to-end guide for setting up, running, migrating, testing, and debugging the Claude MCP workflow server.

---

## 1. Setup & Environment

### Prerequisites

| Requirement | Version |
|-------------|---------|
| Python      | 3.10+   |
| pip         | 23+     |

### Clone & install

```bash
git clone <repo-url> BissetMCP
cd BissetMCP

# Create isolated environment
python3 -m venv .venv
source .venv/bin/activate          # Windows: .venv\Scripts\activate

# Install runtime + test dependencies
pip install -r claude/requirements.txt
```

### Environment variables

Copy the example and fill in your values:

```bash
cp claude/.env.example claude/.env
```

| Variable                  | Required | Default                          | Description                          |
|---------------------------|----------|----------------------------------|--------------------------------------|
| `CLAUDE_API_KEY`          | Yes*     | —                                | Anthropic API key (sk-ant-…)         |
| `CLAUDE_DEFAULT_MODEL`    | No       | `claude-3-5-sonnet-20241022`     | Model used when no override is set   |
| `DATABASE_PATH`           | No       | `./bisset-db/workflow.db`        | SQLite database file path            |
| `WORKFLOW_SERVER_PORT`    | No       | `8765`                           | HTTP port for the workflow server    |
| `WORKFLOW_PRETTY_JSON_LOGS`| No      | `1`                              | `1` = pretty-print JSON logs         |
| `BDD_COVERAGE_THRESHOLD`  | No       | `80`                             | Minimum Gherkin coverage %           |
| `MCP_SERVER_HOST`         | No       | `http://localhost:8765`          | URL the MCP proxy uses to reach backend |

\* Required only if the MCP server makes live Claude API calls.

### Start the workflow server

```bash
cd claude
source ../.venv/bin/activate

# Load env
export $(grep -v '^#' .env | xargs)

uvicorn orchestrator.workflow_server.app:app \
    --host 0.0.0.0 \
    --port "${WORKFLOW_SERVER_PORT:-8765}" \
    --reload            # drop --reload in production
```

### Start the STDIO MCP server

The MCP server is a long-running STDIO process managed by Claude Desktop / the MCP client:

```bash
python -m orchestrator.mcp_server
```

Or with Docker (see §6 Deployment):

```bash
docker compose up
```

---

## 2. Database Migration

The SQLite schema is versioned. Migration runs automatically on startup via `Storage._migrate()`.

### Version history

| Schema | Added                                                        |
|--------|--------------------------------------------------------------|
| v1     | `sessions`, `questions`, `tasks`, `task_test_runs`, `meta`   |
| v2     | Task `description`, `acceptance_criteria` columns           |
| v3     | `task_test_runs.line_coverage_pct`                           |
| v4     | `architecture_proposals`                                     |
| v5     | Unique index on `(session_id, paradigm)`                     |
| v6     | `events` table with indexed `(session_id, timestamp)`        |
| v7     | `sessions.{mcp_client, phase, sub_phase, spec_frozen_at}`, `questions.order_index`, `tasks.assigned_model`, `proposals`, `artifacts`, `background_jobs` |

### v6 → v7 migration guide

1. **Back up your database**:

   ```bash
   cp bisset-db/workflow.db bisset-db/workflow.db.v6.bak
   ```

2. **Start the server** — migration runs automatically:

   ```bash
   uvicorn orchestrator.workflow_server.app:app --port 8765
   ```

3. **Verify**:

   ```bash
   sqlite3 bisset-db/workflow.db \
     "SELECT version FROM schema_version ORDER BY version DESC LIMIT 1;"
   # Expected: 7
   ```

### Manual schema inspection

```bash
sqlite3 bisset-db/workflow.db ".tables"
sqlite3 bisset-db/workflow.db "PRAGMA table_info(sessions);"
```

---

## 3. Testing Strategy

### Test structure

```
claude/orchestrator/
├── workflow_server/tests/
│   ├── test_storage_v7.py   # Storage DAL unit tests (schema, CRUD, migration)
│   ├── test_app.py          # FastAPI endpoint tests (response wrapper, format)
│   └── test_engine.py       # WorkflowEngine unit tests (model routing, job lifecycle)
└── mcp_server/tests/
    ├── test_server.py        # MCP STDIO proxy tests
    └── test_prompts.py       # Prompt rendering tests
```

### Running tests

```bash
# From repo root
python3 -m pytest claude/orchestrator/ -q

# With verbose output
python3 -m pytest claude/orchestrator/ -v

# Single module
python3 -m pytest claude/orchestrator/workflow_server/tests/test_storage_v7.py -v

# Coverage report
python3 -m pytest claude/orchestrator/ --cov=orchestrator --cov-report=term-missing
```

### Test categories

| Category    | What it tests                                    | Isolation |
|-------------|--------------------------------------------------|-----------|
| Unit        | `Storage`, `ComplexityAnalyzer`, `ResponseWrapper` | In-memory SQLite / pure Python |
| Integration | FastAPI endpoints via `TestClient`               | `TestClient` (no real HTTP)    |
| Migration   | Schema v6→v7 auto-migration                      | Temporary directory SQLite     |

### Adding new tests

1. Use `tempfile.TemporaryDirectory()` for SQLite tests — never use a shared path.
2. Mock `app.state.db` and `app.state.engine` in endpoint tests to avoid requiring a live database.
3. Follow the existing `pytest` class-per-module pattern.

---

## 4. Debugging & Troubleshooting

### Structured logs

Set `WORKFLOW_PRETTY_JSON_LOGS=1` to get indented JSON logs. Logs are written to stdout.

```bash
WORKFLOW_PRETTY_JSON_LOGS=1 uvicorn orchestrator.workflow_server.app:app --port 8765
```

### Common errors

| Symptom | Likely cause | Fix |
|---------|--------------|-----|
| `RuntimeError: No active session` | Storage method called with no active session and no explicit `session_id` | Pass `session_id` explicitly, or call `set_active_session()` first |
| `OperationalError: no such column: mcp_client` | Database not migrated to v7 | Restart the server; migration is automatic |
| `ConnectionRefusedError` on MCP proxy startup | Workflow server not running | Start the workflow server first |
| `404 NOT_FOUND` on `/workflow_get_spec` | No answered questions | Complete the interview phase first |
| `500 SESSION_CREATE_ERROR` | `DATABASE_PATH` directory not writable | Check permissions on `bisset-db/` |

### Event log inspection

```bash
# Last 20 events for a session
curl "http://localhost:8765/workflow_get_events/<session_id>?limit=20" | python3 -m json.tool
```

### SQLite direct inspection

```bash
sqlite3 bisset-db/workflow.db \
  "SELECT id, phase, mcp_client FROM sessions ORDER BY created_at DESC LIMIT 5;"

sqlite3 bisset-db/workflow.db \
  "SELECT id, agent_name, status FROM background_jobs WHERE session_id='<sid>';"
```

### Recovery from failed migration

If a migration fails partway:

```bash
# Restore backup
cp bisset-db/workflow.db.v6.bak bisset-db/workflow.db

# Force version reset (use with care)
sqlite3 bisset-db/workflow.db "UPDATE schema_version SET version=6;"
```

---

## 5. Configuration Reference

All variables are read from the process environment or `claude/.env`.

```dotenv
# Anthropic API key — required for live Claude API calls
CLAUDE_API_KEY=sk-ant-api03-...

# Default model when task has no override
CLAUDE_DEFAULT_MODEL=claude-3-5-sonnet-20241022

# SQLite database file path (created automatically)
DATABASE_PATH=./bisset-db/workflow.db

# HTTP port for the workflow server
WORKFLOW_SERVER_PORT=8765

# Set to 1 for indented JSON logging; 0 for compact (production)
WORKFLOW_PRETTY_JSON_LOGS=1

# Minimum Gherkin scenario pass rate required to advance past coverage phase
BDD_COVERAGE_THRESHOLD=80

# URL the MCP STDIO proxy uses to reach the workflow server
MCP_SERVER_HOST=http://localhost:8765
```

### Docker overrides

When running via `docker compose`, environment variables are injected from the `.env` file in the project root (see `docker-compose.yml`). The `DATABASE_PATH` is automatically remapped to the `bisset-db` named volume:

```yaml
environment:
  DATABASE_PATH: /data/workflow.db
volumes:
  - bisset-db:/data
```
