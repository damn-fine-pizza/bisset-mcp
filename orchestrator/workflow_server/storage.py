import sqlite3
import json
import os
import time
import uuid


class Storage:
    def __init__(self, db_path):
        self.db_path = db_path
        os.makedirs(os.path.dirname(db_path), exist_ok=True)
        self.conn = sqlite3.connect(db_path, check_same_thread=False)
        self._migrate()
        self._active_session_id = None  # set by caller

    # ── schema ────────────────────────────────────────────────────────────────

    def _migrate(self):
        cur = self.conn.cursor()
        # sessions table: one row per project/sprint
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
            description TEXT, acceptance_criteria TEXT,
            PRIMARY KEY (id, session_id)
        )''')
        # migrate existing DBs that lack the new columns
        for col in ('description', 'acceptance_criteria'):
            try:
                cur.execute(f'ALTER TABLE tasks ADD COLUMN {col} TEXT')
            except Exception:
                pass
        cur.execute('''CREATE TABLE IF NOT EXISTS meta (
            k TEXT, session_id TEXT, v TEXT,
            PRIMARY KEY (k, session_id)
        )''')
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
        cur.execute('SELECT id, name, created_at, updated_at FROM sessions ORDER BY created_at DESC')
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

    def add_task(self, tid: str, title: str, description: str = '', acceptance_criteria: str = ''):
        cur = self.conn.cursor()
        cur.execute(
            'INSERT OR REPLACE INTO tasks (id, session_id, title, status, created_at, description, acceptance_criteria) VALUES (?,?,?,?,?,?,?)',
            (tid, self.sid, title, 'pending', time.time(), description or '', acceptance_criteria or ''),
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
        cur.execute('SELECT id, title, status, description, acceptance_criteria FROM tasks WHERE id=? AND session_id=?', (tid, self.sid))
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
        cur.execute('SELECT id, title, status, created_at, done_at, evidence, description, acceptance_criteria FROM tasks WHERE session_id=? ORDER BY created_at',
                    (self.sid,))
        return cur.fetchall()
