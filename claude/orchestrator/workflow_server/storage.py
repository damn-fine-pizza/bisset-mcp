"""
Storage layer for Claude MCP - SQLite persistence with schema v7.
Completely independent implementation - no shared code from copilot/.
"""
import sqlite3
import json
import os
import time
import uuid

SCHEMA_VERSION = 7


class Storage:
    """SQLite-based persistence for Bisset MCP workflow state."""

    def __init__(self, db_path: str = None):
        if db_path is None:
            db_path = os.environ.get('DATABASE_PATH', './bisset-db/workflow.db')
        self.db_path = db_path
        parent = os.path.dirname(db_path)
        if parent:
            os.makedirs(parent, exist_ok=True)
        self.conn = sqlite3.connect(db_path, check_same_thread=False)
        # WAL mode: improves concurrent read/write performance and crash safety
        self.conn.execute('PRAGMA journal_mode=WAL')
        self.conn.execute('PRAGMA synchronous=NORMAL')
        self._migrate()
        self._active_session_id = None

    # ── Schema Migration ──────────────────────────────────────────────────────

    def _current_version(self, cur) -> int:
        cur.execute("SELECT name FROM sqlite_master WHERE type='table' AND name='schema_version'")
        if not cur.fetchone():
            return 0
        cur.execute('SELECT version FROM schema_version ORDER BY version DESC LIMIT 1')
        row = cur.fetchone()
        return row[0] if row else 0

    def _set_version(self, cur, version: int):
        cur.execute('DELETE FROM schema_version')
        cur.execute('INSERT INTO schema_version (version) VALUES (?)', (version,))

    def _migrate(self):
        """Run schema migrations up to current version."""
        cur = self.conn.cursor()
        cur.execute('CREATE TABLE IF NOT EXISTS schema_version (version INTEGER NOT NULL)')
        version = self._current_version(cur)

        # v1: Base schema
        if version < 1:
            cur.execute('''CREATE TABLE IF NOT EXISTS sessions (
                id TEXT PRIMARY KEY,
                name TEXT,
                created_at REAL,
                updated_at REAL
            )''')
            cur.execute('''CREATE TABLE IF NOT EXISTS questions (
                id TEXT, session_id TEXT,
                text TEXT, answer TEXT, answered_at REAL,
                PRIMARY KEY (id, session_id)
            )''')
            cur.execute('''CREATE TABLE IF NOT EXISTS tasks (
                id TEXT, session_id TEXT,
                title TEXT, status TEXT, created_at REAL, done_at REAL, evidence TEXT,
                PRIMARY KEY (id, session_id)
            )''')
            cur.execute('''CREATE TABLE IF NOT EXISTS task_test_runs (
                id TEXT PRIMARY KEY,
                task_id TEXT, session_id TEXT,
                run_at REAL, passed INTEGER, failed INTEGER, total INTEGER,
                coverage_pct REAL, ok INTEGER, runner_output TEXT
            )''')
            cur.execute('''CREATE TABLE IF NOT EXISTS meta (
                k TEXT, session_id TEXT, v TEXT,
                PRIMARY KEY (k, session_id)
            )''')
            self._set_version(cur, 1)

        # v2: Task details
        if version < 2:
            for col in ('description TEXT', 'acceptance_criteria TEXT', 'negative_acceptance_criteria TEXT'):
                try:
                    cur.execute(f'ALTER TABLE tasks ADD COLUMN {col}')
                except Exception:
                    pass
            self._set_version(cur, 2)

        # v3: Line coverage
        if version < 3:
            try:
                cur.execute('ALTER TABLE task_test_runs ADD COLUMN line_coverage_pct REAL')
            except Exception:
                pass
            self._set_version(cur, 3)

        # v4: Architecture proposals
        if version < 4:
            cur.execute('''CREATE TABLE IF NOT EXISTS architecture_proposals (
                id TEXT PRIMARY KEY,
                session_id TEXT,
                paradigm TEXT,
                content TEXT,
                created_at REAL
            )''')
            self._set_version(cur, 4)

        # v5: Unique index on proposals
        if version < 5:
            try:
                cur.execute('CREATE UNIQUE INDEX IF NOT EXISTS idx_proposals_session_paradigm ON architecture_proposals (session_id, paradigm)')
            except Exception:
                pass
            self._set_version(cur, 5)

        # v6: Event log
        if version < 6:
            cur.execute('''CREATE TABLE IF NOT EXISTS events (
                id TEXT PRIMARY KEY,
                session_id TEXT,
                tool_name TEXT NOT NULL,
                args_json TEXT,
                result_json TEXT,
                timestamp REAL NOT NULL,
                success INTEGER NOT NULL DEFAULT 1,
                duration_ms REAL
            )''')
            cur.execute('CREATE INDEX IF NOT EXISTS idx_events_session ON events (session_id, timestamp)')
            self._set_version(cur, 6)

        # v7: Claude MCP enhancements
        if version < 7:
            # Sessions: MCP client type, phase tracking, spec frozen timestamp
            for col in ('mcp_client TEXT', 'phase TEXT', 'sub_phase TEXT', 'spec_frozen_at REAL'):
                try:
                    cur.execute(f'ALTER TABLE sessions ADD COLUMN {col}')
                except Exception:
                    pass

            # Questions: order_index for reproducible interview
            try:
                cur.execute('ALTER TABLE questions ADD COLUMN order_index INTEGER')
            except Exception:
                pass

            # Tasks: assigned_model for Claude model routing
            try:
                cur.execute('ALTER TABLE tasks ADD COLUMN assigned_model TEXT')
            except Exception:
                pass

            # Proposals table: with score field
            cur.execute('''CREATE TABLE IF NOT EXISTS proposals (
                id TEXT PRIMARY KEY,
                session_id TEXT,
                paradigm TEXT,
                content TEXT,
                score REAL,
                created_at REAL
            )''')

            # Artifacts table: file change tracking
            cur.execute('''CREATE TABLE IF NOT EXISTS artifacts (
                id TEXT PRIMARY KEY,
                task_id TEXT,
                session_id TEXT,
                file_path TEXT,
                change_type TEXT,
                diff TEXT,
                created_at REAL
            )''')

            # Background jobs: async agent execution
            cur.execute('''CREATE TABLE IF NOT EXISTS background_jobs (
                id TEXT PRIMARY KEY,
                session_id TEXT,
                agent_name TEXT,
                status TEXT,
                result TEXT,
                created_at REAL,
                updated_at REAL
            )''')

            self._set_version(cur, 7)

        self.conn.commit()

    # ── Session Management ────────────────────────────────────────────────────

    def create_session(self, project_name: str = '', mcp_client: str = 'generic', async_mode: bool = False) -> str:
        """Create a new session and return its ID.

        Args:
            project_name: Human-readable project name.
            mcp_client: MCP client type (e.g. ``claude-mcp``, ``copilot-cli``).
            async_mode: Whether the session uses async sub-agent execution.

        Returns:
            New session UUID (8 chars).
        """
        sid = str(uuid.uuid4())[:8]
        now = time.time()
        self.conn.execute(
            'INSERT INTO sessions (id, name, mcp_client, phase, created_at, updated_at) VALUES (?,?,?,?,?,?)',
            (sid, project_name or sid, mcp_client, 'interview', now, now)
        )
        # Store async_mode in meta
        self.conn.execute(
            'INSERT OR REPLACE INTO meta (k, session_id, v) VALUES (?,?,?)',
            ('async_mode', sid, json.dumps(async_mode))
        )
        self.conn.commit()
        self._active_session_id = sid
        return sid

    def set_active_session(self, session_id: str) -> bool:
        """Activate a session."""
        cur = self.conn.cursor()
        cur.execute('SELECT id FROM sessions WHERE id=?', (session_id,))
        if not cur.fetchone():
            return False
        self._active_session_id = session_id
        return True

    def get_session(self, session_id: str) -> dict | None:
        """Return session as a dict, or None if not found."""
        cur = self.conn.cursor()
        cur.execute(
            'SELECT id, name, created_at, updated_at, mcp_client, phase, sub_phase, spec_frozen_at '
            'FROM sessions WHERE id=?',
            (session_id,)
        )
        row = cur.fetchone()
        if not row:
            return None
        return {
            'id': row[0],
            'name': row[1],
            'created_at': row[2],
            'updated_at': row[3],
            'mcp_client': row[4],
            'phase': row[5] or 'interview',
            'sub_phase': row[6],
            'spec_frozen_at': row[7],
        }

    def get_sessions(self) -> list[dict]:
        """Return all sessions ordered by creation time."""
        cur = self.conn.cursor()
        cur.execute(
            'SELECT id, name, created_at, updated_at, mcp_client, phase, sub_phase, spec_frozen_at '
            'FROM sessions ORDER BY created_at'
        )
        rows = cur.fetchall()
        return [
            {
                'id': r[0],
                'name': r[1],
                'created_at': r[2],
                'updated_at': r[3],
                'mcp_client': r[4],
                'phase': r[5] or 'interview',
                'sub_phase': r[6],
                'spec_frozen_at': r[7],
            }
            for r in rows
        ]

    @property
    def sid(self):
        """Get active session ID."""
        if not self._active_session_id:
            raise RuntimeError('No active session. Call create_session() or set_active_session() first.')
        return self._active_session_id

    def _touch(self):
        """Update session's updated_at timestamp."""
        self.conn.execute('UPDATE sessions SET updated_at=? WHERE id=?', (time.time(), self.sid))
        self.conn.commit()

    # ── Questions ─────────────────────────────────────────────────────────────

    def add_questions(self, questions: list):
        """Add questions (qid, text) to session."""
        cur = self.conn.cursor()
        for qid, text in questions:
            cur.execute('INSERT OR IGNORE INTO questions (id, session_id, text) VALUES (?,?,?)',
                       (qid, self.sid, text))
        self.conn.commit()

    def record_answer(self, qid: str, answer: str):
        """Record an answer to a question."""
        cur = self.conn.cursor()
        cur.execute('UPDATE questions SET answer=?, answered_at=? WHERE id=? AND session_id=?',
                   (answer, time.time(), qid, self.sid))
        self.conn.commit()
        self._touch()

    def list_unanswered(self):
        """Get all unanswered questions."""
        cur = self.conn.cursor()
        cur.execute('SELECT id, text FROM questions WHERE answer IS NULL AND session_id=? ORDER BY id',
                   (self.sid,))
        return cur.fetchall()

    def get_all_answers(self):
        """Get all Q&A pairs."""
        cur = self.conn.cursor()
        cur.execute('SELECT id, text, answer FROM questions WHERE session_id=? ORDER BY id', (self.sid,))
        return cur.fetchall()

    # ── Tasks ─────────────────────────────────────────────────────────────────

    def create_tasks(self, tasks: list):
        """Create initial tasks (tid, title) list."""
        cur = self.conn.cursor()
        for tid, title in tasks:
            cur.execute(
                'INSERT OR IGNORE INTO tasks (id, session_id, title, status, created_at) VALUES (?,?,?,?,?)',
                (tid, self.sid, title, 'pending', time.time())
            )
        self.conn.commit()
        self._touch()

    def add_task(self, tid: str, title: str, description: str = '', acceptance_criteria: str = '',
                negative_acceptance_criteria: str = ''):
        """Add or update a task."""
        cur = self.conn.cursor()
        cur.execute(
            'INSERT OR REPLACE INTO tasks (id, session_id, title, status, created_at, description, acceptance_criteria, negative_acceptance_criteria) '
            'VALUES (?,?,?,?,?,?,?,?)',
            (tid, self.sid, title, 'pending', time.time(), description or '', acceptance_criteria or '',
             negative_acceptance_criteria or '')
        )
        self.conn.commit()
        self._touch()

    def next_pending_task(self):
        """Get next pending task."""
        cur = self.conn.cursor()
        cur.execute(
            "SELECT id, title, description, acceptance_criteria FROM tasks WHERE status='pending' AND session_id=? ORDER BY created_at LIMIT 1",
            (self.sid,)
        )
        return cur.fetchone()

    def accept_task(self, tid: str, evidence: dict):
        """Mark task as done."""
        cur = self.conn.cursor()
        cur.execute(
            'UPDATE tasks SET status=?, done_at=?, evidence=? WHERE id=? AND session_id=?',
            ('done', time.time(), json.dumps(evidence), tid, self.sid)
        )
        self.conn.commit()
        self._touch()

    def list_tasks(self):
        """Get all tasks."""
        cur = self.conn.cursor()
        cur.execute(
            'SELECT id, title, status, created_at, done_at, evidence, description, acceptance_criteria, negative_acceptance_criteria '
            'FROM tasks WHERE session_id=? ORDER BY created_at',
            (self.sid,)
        )
        return cur.fetchall()

    def all_tasks_done(self) -> bool:
        """Check if all tasks are done."""
        cur = self.conn.cursor()
        cur.execute("SELECT COUNT(*) FROM tasks WHERE status!='done' AND session_id=?", (self.sid,))
        (n,) = cur.fetchone()
        return n == 0

    # ── Test Runs ─────────────────────────────────────────────────────────────

    def save_test_run(self, task_id: str, passed: int, failed: int, coverage_pct: float,
                     ok: bool, runner_output: str, line_coverage_pct: float | None = None):
        """Save test run results."""
        run_id = str(uuid.uuid4())[:8]
        self.conn.execute(
            'INSERT INTO task_test_runs (id, task_id, session_id, run_at, passed, failed, total, coverage_pct, '
            'line_coverage_pct, ok, runner_output) VALUES (?,?,?,?,?,?,?,?,?,?,?)',
            (run_id, task_id, self.sid, time.time(), passed, failed, passed + failed, coverage_pct,
             line_coverage_pct, int(ok), runner_output)
        )
        self.conn.commit()
        return run_id

    # ── Meta ──────────────────────────────────────────────────────────────────

    def write_meta(self, k: str, v):
        """Store arbitrary key-value metadata."""
        cur = self.conn.cursor()
        cur.execute('INSERT OR REPLACE INTO meta (k, session_id, v) VALUES (?,?,?)',
                   (k, self.sid, json.dumps(v)))
        self.conn.commit()
        self._touch()

    def read_meta(self, k: str, default=None):
        """Retrieve metadata by key."""
        cur = self.conn.cursor()
        cur.execute('SELECT v FROM meta WHERE k=? AND session_id=?', (k, self.sid))
        row = cur.fetchone()
        if not row:
            return default
        return json.loads(row[0])

    # ── Proposals (v7) ────────────────────────────────────────────────────────

    def add_proposal(self, paradigm: str, content: str, score: float | None = None):
        """Add architecture proposal with optional score."""
        proposal_id = str(uuid.uuid4())[:8]
        self.conn.execute(
            'INSERT OR REPLACE INTO proposals (id, session_id, paradigm, content, score, created_at) '
            'VALUES (?,?,?,?,?,?)',
            (proposal_id, self.sid, paradigm, content, score, time.time())
        )
        self.conn.commit()
        self._touch()
        return proposal_id

    def list_proposals(self):
        """Get all proposals."""
        cur = self.conn.cursor()
        cur.execute(
            'SELECT id, paradigm, content, score, created_at FROM proposals WHERE session_id=? ORDER BY created_at',
            (self.sid,)
        )
        return cur.fetchall()

    # ── Artifacts (v7) ────────────────────────────────────────────────────────

    def add_artifact(self, task_id: str, file_path: str, change_type: str, diff: str = ''):
        """Record a file change artifact."""
        artifact_id = str(uuid.uuid4())[:8]
        self.conn.execute(
            'INSERT INTO artifacts (id, task_id, session_id, file_path, change_type, diff, created_at) '
            'VALUES (?,?,?,?,?,?,?)',
            (artifact_id, task_id, self.sid, file_path, change_type, diff or '', time.time())
        )
        self.conn.commit()
        self._touch()
        return artifact_id

    def list_artifacts_for_task(self, task_id: str):
        """Get artifacts for a task."""
        cur = self.conn.cursor()
        cur.execute(
            'SELECT id, file_path, change_type, created_at FROM artifacts WHERE task_id=? AND session_id=? ORDER BY created_at',
            (task_id, self.sid)
        )
        return cur.fetchall()

    # ── Background Jobs (v7) ──────────────────────────────────────────────────

    def create_background_job(self, agent_name: str, session_id: str = None, task_id: str = None) -> str:
        """Create a background job for async execution.

        Args:
            agent_name: Name of the sub-agent (e.g. ``bisset-interview``).
            session_id: Session to associate the job with; falls back to active session.
            task_id: Optional task the job works on.

        Returns:
            Job ID.
        """
        sid = session_id or self.sid
        job_id = str(uuid.uuid4())[:8]
        now = time.time()
        self.conn.execute(
            'INSERT INTO background_jobs (id, session_id, agent_name, status, created_at, updated_at) '
            'VALUES (?,?,?,?,?,?)',
            (job_id, sid, agent_name, 'created', now, now)
        )
        self.conn.commit()
        return job_id

    def update_background_job(self, job_id: str, status: str, result: dict | None = None):
        """Update job status and optional result."""
        self.conn.execute(
            'UPDATE background_jobs SET status=?, result=?, updated_at=? WHERE id=?',
            (status, json.dumps(result) if result else None, time.time(), job_id)
        )
        self.conn.commit()
        if self._active_session_id:
            self._touch()

    def get_background_job(self, job_id: str):
        """Get job status."""
        cur = self.conn.cursor()
        cur.execute(
            'SELECT id, agent_name, status, result, created_at, updated_at FROM background_jobs '
            'WHERE id=?',
            (job_id,)
        )
        row = cur.fetchone()
        if row:
            return {
                'id': row[0],
                'agent_name': row[1],
                'status': row[2],
                'result': json.loads(row[3]) if row[3] else None,
                'created_at': row[4],
                'updated_at': row[5],
            }
        return None

    def list_background_jobs(self, session_id: str, status: str = None) -> list[dict]:
        """List background jobs for a session, optionally filtered by status."""
        cur = self.conn.cursor()
        if status:
            cur.execute(
                'SELECT id, agent_name, status, result, created_at, updated_at FROM background_jobs '
                'WHERE session_id=? AND status=? ORDER BY created_at',
                (session_id, status)
            )
        else:
            cur.execute(
                'SELECT id, agent_name, status, result, created_at, updated_at FROM background_jobs '
                'WHERE session_id=? ORDER BY created_at',
                (session_id,)
            )
        rows = cur.fetchall()
        return [
            {
                'id': r[0],
                'agent_name': r[1],
                'status': r[2],
                'result': json.loads(r[3]) if r[3] else None,
                'created_at': r[4],
                'updated_at': r[5],
            }
            for r in rows
        ]

    # ── Session Metadata (v7) ─────────────────────────────────────────────────

    def set_mcp_client(self, mcp_client: str):
        """Set MCP client type (copilot-cli|claude-mcp|generic)."""
        self.conn.execute('UPDATE sessions SET mcp_client=? WHERE id=?', (mcp_client, self.sid))
        self.conn.commit()

    def set_phase(self, phase: str, sub_phase: str = ''):
        """Set current phase for replay/recovery."""
        self.conn.execute('UPDATE sessions SET phase=?, sub_phase=? WHERE id=?', (phase, sub_phase, self.sid))
        self.conn.commit()

    def set_spec_frozen_at(self, timestamp: float):
        """Record spec freeze timestamp."""
        self.conn.execute('UPDATE sessions SET spec_frozen_at=? WHERE id=?', (timestamp, self.sid))
        self.conn.commit()

    def get_session_metadata(self):
        """Get full session metadata including v7 fields."""
        cur = self.conn.cursor()
        cur.execute(
            'SELECT id, name, created_at, updated_at, mcp_client, phase, sub_phase, spec_frozen_at FROM sessions WHERE id=?',
            (self.sid,)
        )
        return cur.fetchone()

    # ── Event Log ─────────────────────────────────────────────────────────────

    def log_event(self, tool_name: str, args: dict, result: dict, success: bool = True, duration_ms: float | None = None):
        """Log a tool invocation event."""
        event_id = str(uuid.uuid4())
        self.conn.execute(
            'INSERT INTO events (id, session_id, tool_name, args_json, result_json, timestamp, success, duration_ms) '
            'VALUES (?,?,?,?,?,?,?,?)',
            (event_id, self._active_session_id, tool_name, json.dumps(args), json.dumps(result),
             time.time(), 1 if success else 0, duration_ms)
        )
        self.conn.commit()
        return event_id

    def get_events(self, limit: int = 50) -> list:
        """Get recent events for session."""
        cur = self.conn.cursor()
        if self._active_session_id:
            cur.execute(
                'SELECT tool_name, args_json, result_json, timestamp, success, duration_ms FROM events '
                'WHERE session_id=? ORDER BY timestamp DESC LIMIT ?',
                (self.sid, limit)
            )
        else:
            cur.execute(
                'SELECT tool_name, args_json, result_json, timestamp, success, duration_ms FROM events '
                'ORDER BY timestamp DESC LIMIT ?',
                (limit,)
            )
        rows = cur.fetchall()
        return [
            {
                'tool': r[0],
                'args': json.loads(r[1]) if r[1] else {},
                'result': json.loads(r[2]) if r[2] else {},
                'timestamp': r[3],
                'success': bool(r[4]),
                'duration_ms': r[5],
            }
            for r in rows
        ]

    # ── App-facing query helpers ──────────────────────────────────────────────

    def get_next_question(self, session_id: str) -> dict | None:
        """Return next unanswered question for *session_id* as a dict."""
        cur = self.conn.cursor()
        cur.execute(
            'SELECT id, text FROM questions WHERE answer IS NULL AND session_id=? '
            'ORDER BY COALESCE(order_index, 9999), id LIMIT 1',
            (session_id,)
        )
        row = cur.fetchone()
        if not row:
            return None
        return {'id': row[0], 'text': row[1], 'session_id': session_id}

    def get_questions(self, session_id: str) -> list[dict]:
        """Return all questions with answer status for *session_id*."""
        cur = self.conn.cursor()
        cur.execute(
            'SELECT id, text, answer, answered_at FROM questions WHERE session_id=? '
            'ORDER BY COALESCE(order_index, 9999), id',
            (session_id,)
        )
        rows = cur.fetchall()
        return [
            {
                'id': r[0],
                'text': r[1],
                'answer': r[2],
                'answered_at': r[3],
                'answered': r[2] is not None,
            }
            for r in rows
        ]

    def freeze_spec(self, session_id: str) -> None:
        """Mark spec as frozen for *session_id*."""
        self.conn.execute(
            'UPDATE sessions SET spec_frozen_at=?, phase=? WHERE id=?',
            (time.time(), 'architecture', session_id)
        )
        self.conn.commit()

    def get_next_pending_task(self, session_id: str) -> dict | None:
        """Return the next pending task for *session_id* as a dict."""
        cur = self.conn.cursor()
        cur.execute(
            "SELECT id, title, description, acceptance_criteria, assigned_model FROM tasks "
            "WHERE status='pending' AND session_id=? ORDER BY created_at LIMIT 1",
            (session_id,)
        )
        row = cur.fetchone()
        if not row:
            return None
        return {
            'id': row[0],
            'title': row[1],
            'description': row[2] or '',
            'acceptance_criteria': row[3] or '',
            'assigned_model': row[4],
        }

    def get_task(self, task_id: str) -> dict | None:
        """Return a task by ID as a dict."""
        cur = self.conn.cursor()
        cur.execute(
            'SELECT id, session_id, title, description, status, assigned_model, created_at, done_at '
            'FROM tasks WHERE id=?',
            (task_id,)
        )
        row = cur.fetchone()
        if not row:
            return None
        return {
            'id': row[0],
            'session_id': row[1],
            'title': row[2],
            'description': row[3] or '',
            'status': row[4],
            'assigned_model': row[5],
            'created_at': row[6],
            'done_at': row[7],
        }

    def update_task_model(self, task_id: str, model: str) -> None:
        """Set assigned_model on a task."""
        self.conn.execute(
            'UPDATE tasks SET assigned_model=? WHERE id=?',
            (model, task_id)
        )
        self.conn.commit()

    def update_task_status(self, task_id: str, status: str) -> None:
        """Update task status field."""
        done_at = time.time() if status in ('completed', 'done') else None
        self.conn.execute(
            'UPDATE tasks SET status=?, done_at=? WHERE id=?',
            (status, done_at, task_id)
        )
        self.conn.commit()

    def add_event(self, session_id: str | None, event_type: str, data: dict) -> str:
        """Add a generic event (app-facing alias for log_event).

        Args:
            session_id: Associated session, or None for global events.
            event_type: Logical event type (e.g. ``task_completed``).
            data: Arbitrary event payload.

        Returns:
            Event ID.
        """
        event_id = str(uuid.uuid4())
        self.conn.execute(
            'INSERT INTO events (id, session_id, tool_name, args_json, result_json, timestamp, success, duration_ms) '
            'VALUES (?,?,?,?,?,?,?,?)',
            (event_id, session_id, event_type, json.dumps(data), '{}', time.time(), 1, None)
        )
        self.conn.commit()
        return event_id

    def list_events(self, session_id: str, limit: int = 100) -> list[dict]:
        """Return events for *session_id* ordered newest-first."""
        cur = self.conn.cursor()
        cur.execute(
            'SELECT id, tool_name, args_json, timestamp, success, duration_ms FROM events '
            'WHERE session_id=? ORDER BY timestamp DESC LIMIT ?',
            (session_id, limit)
        )
        rows = cur.fetchall()
        return [
            {
                'id': r[0],
                'event_type': r[1],
                'data': json.loads(r[2]) if r[2] else {},
                'timestamp': r[3],
                'success': bool(r[4]),
                'duration_ms': r[5],
            }
            for r in rows
        ]

    def add_task_for_session(
        self,
        session_id: str,
        title: str,
        description: str = '',
        acceptance_criteria: str = '',
        negative_acceptance_criteria: str = '',
    ) -> str:
        """Add a task to *session_id* (session-ID–explicit variant of add_task)."""
        tid = str(uuid.uuid4())[:8]
        self.conn.execute(
            'INSERT OR REPLACE INTO tasks '
            '(id, session_id, title, status, created_at, description, acceptance_criteria, negative_acceptance_criteria) '
            'VALUES (?,?,?,?,?,?,?,?)',
            (tid, session_id, title, 'pending', time.time(), description, acceptance_criteria,
             negative_acceptance_criteria)
        )
        self.conn.commit()
        return tid

    def save_test_run_for_session(
        self,
        session_id: str,
        task_id: str,
        passed: int,
        failed: int,
        coverage_pct: float,
        ok: bool,
        runner_output: str,
    ) -> str:
        """Save a test run result for *session_id*."""
        run_id = str(uuid.uuid4())[:8]
        self.conn.execute(
            'INSERT INTO task_test_runs '
            '(id, task_id, session_id, run_at, passed, failed, total, coverage_pct, ok, runner_output) '
            'VALUES (?,?,?,?,?,?,?,?,?,?)',
            (run_id, task_id, session_id, time.time(), passed, failed, passed + failed,
             coverage_pct, int(ok), runner_output)
        )
        self.conn.commit()
        return run_id

    def close(self):
        """Close the database connection."""
        self.conn.close()
