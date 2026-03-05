import sqlite3
import json
import os
import time
import uuid

SCHEMA_VERSION = 6


class Storage:
    def __init__(self, db_path):
        self.db_path = db_path
        os.makedirs(os.path.dirname(db_path), exist_ok=True)
        self.conn = sqlite3.connect(db_path, check_same_thread=False)
        # WAL mode: improves concurrent read/write performance and crash safety
        self.conn.execute('PRAGMA journal_mode=WAL')
        self.conn.execute('PRAGMA synchronous=NORMAL')
        self._migrate()
        self._active_session_id = None  # set by caller

    # ── schema ────────────────────────────────────────────────────────────────

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
        cur = self.conn.cursor()
        cur.execute('CREATE TABLE IF NOT EXISTS schema_version (version INTEGER NOT NULL)')
        version = self._current_version(cur)

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

        if version < 2:
            # add task detail columns
            for col in ('description TEXT', 'acceptance_criteria TEXT', 'negative_acceptance_criteria TEXT'):
                try:
                    cur.execute(f'ALTER TABLE tasks ADD COLUMN {col}')
                except Exception:
                    pass
            self._set_version(cur, 2)

        if version < 3:
            # add line coverage to test runs
            try:
                cur.execute('ALTER TABLE task_test_runs ADD COLUMN line_coverage_pct REAL')
            except Exception:
                pass
            self._set_version(cur, 3)

        if version < 4:
            # architecture proposals table
            cur.execute('''CREATE TABLE IF NOT EXISTS architecture_proposals (
                id TEXT PRIMARY KEY,
                session_id TEXT,
                paradigm TEXT,
                content TEXT,
                created_at REAL
            )''')
            self._set_version(cur, 4)

        if version < 5:
            # enforce UNIQUE on architecture_proposals (paradigm, session_id) via index
            try:
                cur.execute('CREATE UNIQUE INDEX IF NOT EXISTS idx_proposals_session_paradigm ON architecture_proposals (session_id, paradigm)')
            except Exception:
                pass
            self._set_version(cur, 5)

        if version < 6:
            # execution event log for debug / replay / recovery
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
            # index for efficient session-scoped queries
            cur.execute('CREATE INDEX IF NOT EXISTS idx_events_session ON events (session_id, timestamp)')
            self._set_version(cur, 6)

        self.conn.commit()


    # ── session management ────────────────────────────────────────────────────

    def create_session(self, name: str = '') -> str:
        sid = str(uuid.uuid4())[:8]
        now = time.time()
        self.conn.execute(
            'INSERT INTO sessions (id, name, created_at, updated_at) VALUES (?,?,?,?)',
            (sid, name or sid, now, now)
        )
        self.conn.commit()
        self._active_session_id = sid
        return sid

    def set_active_session(self, session_id: str) -> bool:
        cur = self.conn.cursor()
        cur.execute('SELECT id FROM sessions WHERE id=?', (session_id,))
        if not cur.fetchone():
            return False
        self._active_session_id = session_id
        return True

    def list_sessions(self):
        cur = self.conn.cursor()
        cur.execute('''
            SELECT s.id, s.name, s.created_at, s.updated_at,
                   MAX(CASE WHEN m.k="phase" THEN m.v END) as phase,
                   MAX(CASE WHEN m.k="sub_phase" THEN m.v END) as sub_phase,
                   COUNT(DISTINCT CASE WHEN t.status="done" THEN t.id END) as tasks_done,
                   COUNT(DISTINCT t.id) as tasks_total,
                   COUNT(DISTINCT CASE WHEN q.answer IS NOT NULL THEN q.id END) as questions_answered
            FROM sessions s
            LEFT JOIN meta m ON m.session_id = s.id
            LEFT JOIN tasks t ON t.session_id = s.id
            LEFT JOIN questions q ON q.session_id = s.id
            GROUP BY s.id
            ORDER BY s.updated_at DESC
        ''')
        return cur.fetchall()

    def get_session(self, session_id: str):
        cur = self.conn.cursor()
        cur.execute('SELECT id, name, created_at, updated_at FROM sessions WHERE id=?', (session_id,))
        return cur.fetchone()

    @property
    def sid(self):
        if not self._active_session_id:
            raise RuntimeError('No active session. Call create_session() or set_active_session() first.')
        return self._active_session_id

    def _touch(self):
        self.conn.execute('UPDATE sessions SET updated_at=? WHERE id=?', (time.time(), self.sid))
        self.conn.commit()

    # ── questions ─────────────────────────────────────────────────────────────

    def list_unanswered(self):
        cur = self.conn.cursor()
        cur.execute('SELECT id, text FROM questions WHERE answer IS NULL AND session_id=? ORDER BY id', (self.sid,))
        return cur.fetchall()

    def add_questions(self, questions):
        cur = self.conn.cursor()
        for qid, text in questions:
            cur.execute('INSERT OR IGNORE INTO questions (id, session_id, text) VALUES (?,?,?)', (qid, self.sid, text))
        self.conn.commit()

    def record_answer(self, qid, answer):
        cur = self.conn.cursor()
        cur.execute('UPDATE questions SET answer=?, answered_at=? WHERE id=? AND session_id=?',
                    (answer, time.time(), qid, self.sid))
        self.conn.commit()
        self._touch()

    def get_all_answers(self):
        cur = self.conn.cursor()
        cur.execute('SELECT id, text, answer FROM questions WHERE session_id=? ORDER BY id', (self.sid,))
        return cur.fetchall()

    # ── meta ──────────────────────────────────────────────────────────────────

    def write_meta(self, k, v):
        cur = self.conn.cursor()
        cur.execute('INSERT OR REPLACE INTO meta (k, session_id, v) VALUES (?,?,?)', (k, self.sid, json.dumps(v)))
        self.conn.commit()
        self._touch()

    def read_meta(self, k, default=None):
        cur = self.conn.cursor()
        cur.execute('SELECT v FROM meta WHERE k=? AND session_id=?', (k, self.sid))
        row = cur.fetchone()
        if not row:
            return default
        return json.loads(row[0])

    # ── tasks ─────────────────────────────────────────────────────────────────

    def create_tasks(self, tasks):
        cur = self.conn.cursor()
        for tid, title in tasks:
            cur.execute('INSERT OR IGNORE INTO tasks (id, session_id, title, status, created_at) VALUES (?,?,?,?,?)',
                        (tid, self.sid, title, 'pending', time.time()))
        self.conn.commit()
        self._touch()

    def add_task(self, tid: str, title: str, description: str = '', acceptance_criteria: str = '', negative_acceptance_criteria: str = ''):
        cur = self.conn.cursor()
        cur.execute(
            'INSERT OR REPLACE INTO tasks (id, session_id, title, status, created_at, description, acceptance_criteria, negative_acceptance_criteria) VALUES (?,?,?,?,?,?,?,?)',
            (tid, self.sid, title, 'pending', time.time(), description or '', acceptance_criteria or '', negative_acceptance_criteria or ''),
        )
        self.conn.commit()
        self._touch()

    def next_pending_task(self):
        cur = self.conn.cursor()
        cur.execute("SELECT id, title, description, acceptance_criteria FROM tasks WHERE status='pending' AND session_id=? ORDER BY created_at LIMIT 1",
                    (self.sid,))
        return cur.fetchone()

    def get_task(self, tid: str):
        cur = self.conn.cursor()
        cur.execute('SELECT id, title, status, description, acceptance_criteria, negative_acceptance_criteria FROM tasks WHERE id=? AND session_id=?', (tid, self.sid))
        return cur.fetchone()

    def accept_task(self, tid, evidence):
        cur = self.conn.cursor()
        cur.execute('UPDATE tasks SET status=?, done_at=?, evidence=? WHERE id=? AND session_id=?',
                    ('done', time.time(), json.dumps(evidence), tid, self.sid))
        self.conn.commit()
        self._touch()

    def all_tasks_done(self):
        cur = self.conn.cursor()
        cur.execute("SELECT COUNT(*) FROM tasks WHERE status!='done' AND session_id=?", (self.sid,))
        (n,) = cur.fetchone()
        return n == 0

    def list_tasks(self):
        cur = self.conn.cursor()
        cur.execute('SELECT id, title, status, created_at, done_at, evidence, description, acceptance_criteria, negative_acceptance_criteria FROM tasks WHERE session_id=? ORDER BY created_at',
                    (self.sid,))
        return cur.fetchall()

    # ── test runs ─────────────────────────────────────────────────────────────

    def save_test_run(self, task_id: str, passed: int, failed: int, coverage_pct: float, ok: bool, runner_output: str, line_coverage_pct: float | None = None):
        run_id = str(uuid.uuid4())[:8]
        self.conn.execute(
            'INSERT INTO task_test_runs (id, task_id, session_id, run_at, passed, failed, total, coverage_pct, line_coverage_pct, ok, runner_output) VALUES (?,?,?,?,?,?,?,?,?,?,?)',
            (run_id, task_id, self.sid, time.time(), passed, failed, passed + failed, coverage_pct, line_coverage_pct, int(ok), runner_output),
        )
        self.conn.commit()
        return run_id

    def get_last_passing_run(self, task_id: str):
        cur = self.conn.cursor()
        cur.execute(
            'SELECT id, passed, failed, total, coverage_pct, line_coverage_pct, run_at FROM task_test_runs WHERE task_id=? AND session_id=? AND ok=1 ORDER BY run_at DESC LIMIT 1',
            (task_id, self.sid),
        )
        return cur.fetchone()

    # ── architecture proposals ────────────────────────────────────────────────

    def add_proposal(self, paradigm: str, content: str):
        proposal_id = str(uuid.uuid4())[:8]
        self.conn.execute(
            'INSERT OR REPLACE INTO architecture_proposals (id, session_id, paradigm, content, created_at) VALUES (?,?,?,?,?)',
            (proposal_id, self.sid, paradigm, content, time.time()),
        )
        self.conn.commit()
        self._touch()
        return proposal_id

    def list_proposals(self):
        cur = self.conn.cursor()
        cur.execute(
            'SELECT paradigm, content, created_at FROM architecture_proposals WHERE session_id=? ORDER BY created_at',
            (self.sid,),
        )
        return cur.fetchall()

    # ── event log ────────────────────────────────────────────────────────────

    def log_event(self, tool_name: str, args: dict, result: dict,
                  success: bool = True, duration_ms: float | None = None):
        """Record a tool invocation for debug / replay purposes."""
        event_id = str(uuid.uuid4())
        sid = self._active_session_id  # may be None before session is created
        self.conn.execute(
            'INSERT INTO events (id, session_id, tool_name, args_json, result_json, timestamp, success, duration_ms) VALUES (?,?,?,?,?,?,?,?)',
            (event_id, sid, tool_name, json.dumps(args), json.dumps(result),
             time.time(), 1 if success else 0, duration_ms),
        )
        self.conn.commit()
        return event_id

    def get_events(self, limit: int = 50) -> list:
        """Return the most recent ``limit`` events for the active session."""
        cur = self.conn.cursor()
        if self._active_session_id:
            cur.execute(
                'SELECT tool_name, args_json, result_json, timestamp, success, duration_ms FROM events WHERE session_id=? ORDER BY timestamp DESC LIMIT ?',
                (self.sid, limit),
            )
        else:
            cur.execute(
                'SELECT tool_name, args_json, result_json, timestamp, success, duration_ms FROM events ORDER BY timestamp DESC LIMIT ?',
                (limit,),
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
