import sqlite3
import json
import os
import time

class Storage:
    def __init__(self, db_path):
        self.db_path = db_path
        os.makedirs(os.path.dirname(db_path), exist_ok=True)
        self.conn = sqlite3.connect(db_path, check_same_thread=False)
        self._migrate()

    def _migrate(self):
        cur = self.conn.cursor()
        cur.execute('''CREATE TABLE IF NOT EXISTS questions (id TEXT PRIMARY KEY, text TEXT, answer TEXT, answered_at REAL)''')
        cur.execute('''CREATE TABLE IF NOT EXISTS tasks (id TEXT PRIMARY KEY, title TEXT, status TEXT, created_at REAL, done_at REAL, evidence TEXT)''')
        cur.execute('''CREATE TABLE IF NOT EXISTS meta (k TEXT PRIMARY KEY, v TEXT)''')
        self.conn.commit()

    def list_unanswered(self):
        cur = self.conn.cursor()
        cur.execute("SELECT id, text FROM questions WHERE answer IS NULL ORDER BY id")
        return cur.fetchall()

    def add_questions(self, questions):
        cur = self.conn.cursor()
        for qid, text in questions:
            cur.execute('INSERT OR IGNORE INTO questions (id, text) VALUES (?,?)', (qid, text))
        self.conn.commit()

    def record_answer(self, qid, answer):
        cur = self.conn.cursor()
        cur.execute('UPDATE questions SET answer=?, answered_at=? WHERE id=?', (answer, time.time(), qid))
        self.conn.commit()

    def get_all_answers(self):
        cur = self.conn.cursor()
        cur.execute('SELECT id, text, answer FROM questions ORDER BY id')
        return cur.fetchall()

    def write_meta(self, k, v):
        cur = self.conn.cursor()
        cur.execute('INSERT OR REPLACE INTO meta (k,v) VALUES (?,?)', (k, json.dumps(v)))
        self.conn.commit()

    def read_meta(self, k, default=None):
        cur = self.conn.cursor()
        cur.execute('SELECT v FROM meta WHERE k=?', (k,))
        row = cur.fetchone()
        if not row:
            return default
        return json.loads(row[0])

    def create_tasks(self, tasks):
        cur = self.conn.cursor()
        for tid, title in tasks:
            cur.execute('INSERT OR IGNORE INTO tasks (id,title,status,created_at) VALUES (?,?,?,?)', (tid, title, 'pending', time.time()))
        self.conn.commit()

    def next_pending_task(self):
        cur = self.conn.cursor()
        cur.execute("SELECT id, title FROM tasks WHERE status='pending' ORDER BY created_at LIMIT 1")
        return cur.fetchone()

    def accept_task(self, tid, evidence):
        cur = self.conn.cursor()
        cur.execute('UPDATE tasks SET status=?, done_at=?, evidence=? WHERE id=?', ('done', time.time(), json.dumps(evidence), tid))
        self.conn.commit()

    def all_tasks_done(self):
        cur = self.conn.cursor()
        cur.execute("SELECT COUNT(*) FROM tasks WHERE status!='done'")
        (n,) = cur.fetchone()
        return n == 0

    def list_tasks(self):
        cur = self.conn.cursor()
        cur.execute('SELECT id,title,status,created_at,done_at,evidence FROM tasks ORDER BY created_at')
        return cur.fetchall()
