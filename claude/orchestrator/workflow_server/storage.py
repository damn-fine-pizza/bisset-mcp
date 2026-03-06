"""Storage layer for Bisset v2 - SQLite persistence with fresh schema."""
import json
import os
import sqlite3
import time
import uuid

SCHEMA_VERSION = 1


class Storage:
    """SQLite-based persistence for Bisset v2 workflow state.

    Write isolation: all write operations require a locked project
    (set via ``lock_project``).  Read operations accept an optional
    ``project_id`` filter but do not require a lock.
    """

    def __init__(self, db_path: str = None):
        if db_path is None:
            base = os.path.expanduser("~/.bisset")
            os.makedirs(base, exist_ok=True)
            db_path = os.path.join(base, "bisset.db")
        self.db_path = db_path

        # Create parent directory for non-memory databases
        if db_path != ":memory:":
            parent = os.path.dirname(db_path)
            if parent:
                os.makedirs(parent, exist_ok=True)

        self.conn = sqlite3.connect(db_path, check_same_thread=False)
        self.conn.execute("PRAGMA journal_mode=WAL")
        self.conn.execute("PRAGMA synchronous=NORMAL")
        self.conn.execute("PRAGMA foreign_keys=ON")
        self._locked_project_id: str | None = None
        self._migrate()

    # ── Helpers ────────────────────────────────────────────────────────────────

    @staticmethod
    def _new_id() -> str:
        return str(uuid.uuid4())[:8]

    def _require_lock(self) -> str:
        """Return locked project id or raise."""
        if self._locked_project_id is None:
            raise RuntimeError(
                "No project locked. Call lock_project() before write operations."
            )
        return self._locked_project_id

    @staticmethod
    def _row_to_dict(cursor: sqlite3.Cursor, row: tuple) -> dict:
        """Convert a row tuple to a dict using cursor.description."""
        return {
            col[0]: row[i] for i, col in enumerate(cursor.description)
        }

    def _fetchone_dict(self, sql: str, params: tuple = ()) -> dict | None:
        cur = self.conn.execute(sql, params)
        row = cur.fetchone()
        if row is None:
            return None
        return self._row_to_dict(cur, row)

    def _fetchall_dict(self, sql: str, params: tuple = ()) -> list[dict]:
        cur = self.conn.execute(sql, params)
        rows = cur.fetchall()
        return [self._row_to_dict(cur, r) for r in rows]

    # ── Schema Migration ──────────────────────────────────────────────────────

    def _migrate(self):
        """Create v1 schema from scratch (no legacy migration)."""
        cur = self.conn.cursor()

        cur.execute(
            "SELECT name FROM sqlite_master WHERE type='table' AND name='schema_version'"
        )
        if cur.fetchone():
            cur.execute(
                "SELECT version FROM schema_version ORDER BY version DESC LIMIT 1"
            )
            row = cur.fetchone()
            if row and row[0] >= SCHEMA_VERSION:
                return

        cur.executescript("""
            CREATE TABLE IF NOT EXISTS schema_version (
                version INTEGER NOT NULL
            );

            CREATE TABLE IF NOT EXISTS projects (
                id TEXT PRIMARY KEY,
                name TEXT NOT NULL,
                path TEXT NOT NULL UNIQUE,
                test_runner TEXT NOT NULL DEFAULT 'generic',
                test_args TEXT NOT NULL DEFAULT '',
                adapter TEXT NOT NULL DEFAULT 'generic',
                features_dir TEXT NOT NULL DEFAULT 'features/',
                created_at REAL NOT NULL
            );

            CREATE TABLE IF NOT EXISTS sessions (
                id TEXT PRIMARY KEY,
                project_id TEXT NOT NULL REFERENCES projects(id),
                workflow_type TEXT NOT NULL,
                status TEXT NOT NULL DEFAULT 'active',
                default_rules TEXT,
                created_at REAL NOT NULL
            );

            CREATE TABLE IF NOT EXISTS steps (
                id TEXT PRIMARY KEY,
                session_id TEXT NOT NULL REFERENCES sessions(id),
                title TEXT NOT NULL,
                description TEXT NOT NULL DEFAULT '',
                "order" INTEGER NOT NULL,
                feature_path TEXT,
                gate TEXT NOT NULL DEFAULT 'tests_only',
                depends_on TEXT,
                rules_override TEXT,
                status TEXT NOT NULL DEFAULT 'pending',
                retries INTEGER NOT NULL DEFAULT 0,
                current_coverage REAL NOT NULL DEFAULT 0.0,
                gate_result TEXT,
                created_at REAL NOT NULL
            );

            CREATE TABLE IF NOT EXISTS test_runs (
                id TEXT PRIMARY KEY,
                step_id TEXT NOT NULL REFERENCES steps(id),
                session_id TEXT NOT NULL REFERENCES sessions(id),
                run_at REAL NOT NULL,
                passed INTEGER NOT NULL DEFAULT 0,
                failed INTEGER NOT NULL DEFAULT 0,
                coverage REAL NOT NULL DEFAULT 0.0,
                runner_output TEXT NOT NULL DEFAULT ''
            );

            CREATE TABLE IF NOT EXISTS events (
                id TEXT PRIMARY KEY,
                session_id TEXT NOT NULL REFERENCES sessions(id),
                event_type TEXT NOT NULL,
                step_id TEXT,
                data TEXT,
                timestamp REAL NOT NULL
            );
        """)

        cur.execute("DELETE FROM schema_version")
        cur.execute(
            "INSERT INTO schema_version (version) VALUES (?)", (SCHEMA_VERSION,)
        )
        self.conn.commit()

    # ── Project ───────────────────────────────────────────────────────────────

    def create_project(
        self,
        name: str,
        path: str,
        test_runner: str = "generic",
        test_args: str = "",
        adapter: str = "generic",
        features_dir: str = "features/",
    ) -> str:
        pid = self._new_id()
        self.conn.execute(
            "INSERT INTO projects (id, name, path, test_runner, test_args, adapter, features_dir, created_at) "
            "VALUES (?,?,?,?,?,?,?,?)",
            (pid, name, path, test_runner, test_args, adapter, features_dir, time.time()),
        )
        self.conn.commit()
        return pid

    def get_project(self, project_id: str) -> dict | None:
        return self._fetchone_dict(
            "SELECT * FROM projects WHERE id=?", (project_id,)
        )

    def get_project_by_path(self, path: str) -> dict | None:
        return self._fetchone_dict(
            "SELECT * FROM projects WHERE path=?", (path,)
        )

    def list_projects(self) -> list[dict]:
        return self._fetchall_dict("SELECT * FROM projects ORDER BY created_at")

    def lock_project(self, project_id: str) -> bool:
        proj = self.get_project(project_id)
        if proj is None:
            return False
        self._locked_project_id = project_id
        return True

    def update_project(self, project_id: str, **kwargs) -> None:
        if not kwargs:
            return
        allowed = {"name", "path", "test_runner", "test_args", "adapter", "features_dir"}
        sets = []
        vals = []
        for k, v in kwargs.items():
            if k not in allowed:
                raise ValueError(f"Unknown project field: {k}")
            sets.append(f"{k}=?")
            vals.append(v)
        vals.append(project_id)
        self.conn.execute(
            f"UPDATE projects SET {', '.join(sets)} WHERE id=?", tuple(vals)
        )
        self.conn.commit()

    # ── Session ───────────────────────────────────────────────────────────────

    def create_session(
        self, workflow_type: str, default_rules: dict | None = None
    ) -> str:
        project_id = self._require_lock()
        sid = self._new_id()
        self.conn.execute(
            "INSERT INTO sessions (id, project_id, workflow_type, status, default_rules, created_at) "
            "VALUES (?,?,?,?,?,?)",
            (
                sid,
                project_id,
                workflow_type,
                "active",
                json.dumps(default_rules) if default_rules else None,
                time.time(),
            ),
        )
        self.conn.commit()
        return sid

    def get_session(self, session_id: str) -> dict | None:
        row = self._fetchone_dict(
            "SELECT * FROM sessions WHERE id=?", (session_id,)
        )
        if row and row.get("default_rules"):
            row["default_rules"] = json.loads(row["default_rules"])
        return row

    def list_sessions(self, project_id: str = None) -> list[dict]:
        if project_id:
            return self._fetchall_dict(
                "SELECT * FROM sessions WHERE project_id=? ORDER BY created_at",
                (project_id,),
            )
        return self._fetchall_dict("SELECT * FROM sessions ORDER BY created_at")

    def update_session_status(self, session_id: str, status: str) -> None:
        self.conn.execute(
            "UPDATE sessions SET status=? WHERE id=?", (status, session_id)
        )
        self.conn.commit()

    # ── Step ──────────────────────────────────────────────────────────────────

    def add_step(
        self,
        session_id: str,
        title: str,
        description: str,
        order: int,
        *,
        feature_path: str = None,
        gate: str = "tests_only",
        depends_on: list[str] = None,
        rules_override: dict = None,
    ) -> str:
        self._require_lock()
        step_id = self._new_id()
        self.conn.execute(
            'INSERT INTO steps (id, session_id, title, description, "order", feature_path, '
            "gate, depends_on, rules_override, status, retries, current_coverage, created_at) "
            "VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?)",
            (
                step_id,
                session_id,
                title,
                description,
                order,
                feature_path,
                gate,
                json.dumps(depends_on) if depends_on else None,
                json.dumps(rules_override) if rules_override else None,
                "pending",
                0,
                0.0,
                time.time(),
            ),
        )
        self.conn.commit()
        return step_id

    def get_step(self, step_id: str) -> dict | None:
        row = self._fetchone_dict("SELECT * FROM steps WHERE id=?", (step_id,))
        if row:
            if row.get("depends_on"):
                row["depends_on"] = json.loads(row["depends_on"])
            if row.get("rules_override"):
                row["rules_override"] = json.loads(row["rules_override"])
        return row

    def list_steps(self, session_id: str) -> list[dict]:
        return self._fetchall_dict(
            'SELECT * FROM steps WHERE session_id=? ORDER BY "order"',
            (session_id,),
        )

    def update_step(self, step_id: str, **kwargs) -> None:
        if not kwargs:
            return
        allowed = {
            "title",
            "description",
            "order",
            "feature_path",
            "gate",
            "depends_on",
            "rules_override",
            "status",
            "retries",
            "current_coverage",
            "gate_result",
        }
        sets = []
        vals = []
        for k, v in kwargs.items():
            if k not in allowed:
                raise ValueError(f"Unknown step field: {k}")
            col = f'"{k}"' if k == "order" else k
            sets.append(f"{col}=?")
            if k in ("depends_on", "rules_override") and v is not None:
                v = json.dumps(v)
            vals.append(v)
        vals.append(step_id)
        self.conn.execute(
            f"UPDATE steps SET {', '.join(sets)} WHERE id=?", tuple(vals)
        )
        self.conn.commit()

    def remove_step(self, step_id: str) -> bool:
        cur = self.conn.execute("DELETE FROM steps WHERE id=?", (step_id,))
        self.conn.commit()
        return cur.rowcount > 0

    def get_current_step(self, session_id: str) -> dict | None:
        # First try active
        row = self._fetchone_dict(
            "SELECT * FROM steps WHERE session_id=? AND status='active' "
            'ORDER BY "order" LIMIT 1',
            (session_id,),
        )
        if row:
            return row
        # Fall back to first pending
        return self._fetchone_dict(
            "SELECT * FROM steps WHERE session_id=? AND status='pending' "
            'ORDER BY "order" LIMIT 1',
            (session_id,),
        )

    def reorder_steps(self, session_id: str, step_ids: list[str]) -> None:
        cur = self.conn.cursor()
        for idx, sid in enumerate(step_ids):
            cur.execute(
                'UPDATE steps SET "order"=? WHERE id=? AND session_id=?',
                (idx, sid, session_id),
            )
        self.conn.commit()

    # ── Test Run ──────────────────────────────────────────────────────────────

    def add_test_run(
        self,
        step_id: str,
        session_id: str,
        passed: int,
        failed: int,
        coverage: float,
        runner_output: str,
    ) -> str:
        run_id = self._new_id()
        self.conn.execute(
            "INSERT INTO test_runs (id, step_id, session_id, run_at, passed, failed, coverage, runner_output) "
            "VALUES (?,?,?,?,?,?,?,?)",
            (run_id, step_id, session_id, time.time(), passed, failed, coverage, runner_output),
        )
        self.conn.commit()
        return run_id

    def get_test_run(self, run_id: str) -> dict | None:
        return self._fetchone_dict(
            "SELECT * FROM test_runs WHERE id=?", (run_id,)
        )

    def get_latest_test_run(self, step_id: str) -> dict | None:
        return self._fetchone_dict(
            "SELECT * FROM test_runs WHERE step_id=? ORDER BY run_at DESC LIMIT 1",
            (step_id,),
        )

    # ── Event ─────────────────────────────────────────────────────────────────

    def add_event(
        self,
        session_id: str,
        event_type: str,
        *,
        step_id: str = None,
        data: dict = None,
    ) -> str:
        ev_id = self._new_id()
        self.conn.execute(
            "INSERT INTO events (id, session_id, event_type, step_id, data, timestamp) "
            "VALUES (?,?,?,?,?,?)",
            (
                ev_id,
                session_id,
                event_type,
                step_id,
                json.dumps(data) if data else None,
                time.time(),
            ),
        )
        self.conn.commit()
        return ev_id

    def list_events(self, session_id: str, limit: int = 100) -> list[dict]:
        rows = self._fetchall_dict(
            "SELECT * FROM events WHERE session_id=? ORDER BY timestamp DESC LIMIT ?",
            (session_id, limit),
        )
        for r in rows:
            if r.get("data"):
                r["data"] = json.loads(r["data"])
        return rows

    # ── Lifecycle ─────────────────────────────────────────────────────────────

    def close(self):
        """Close the database connection."""
        self.conn.close()
