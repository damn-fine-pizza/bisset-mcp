"""Tests for Bisset v2 Storage layer."""
import pytest
from orchestrator.workflow_server.storage import Storage


@pytest.fixture
def db():
    s = Storage(db_path=":memory:")
    yield s
    s.close()


def test_create_project(db):
    pid = db.create_project("myapp", "/tmp/myapp", "pytest", "", "pytest", "features/")
    proj = db.get_project(pid)
    assert proj is not None
    assert proj["name"] == "myapp"
    assert proj["path"] == "/tmp/myapp"
    assert proj["test_runner"] == "pytest"


def test_create_session(db):
    pid = db.create_project("myapp", "/tmp/myapp", "pytest", "", "pytest", "features/")
    db.lock_project(pid)
    sid = db.create_session("new_project")
    sess = db.get_session(sid)
    assert sess is not None
    assert sess["workflow_type"] == "new_project"
    assert sess["status"] == "active"
    assert sess["project_id"] == pid


def test_write_isolation_locked_project(db):
    pid1 = db.create_project("app1", "/tmp/app1", "pytest", "", "pytest", "features/")
    pid2 = db.create_project("app2", "/tmp/app2", "pytest", "", "pytest", "features/")
    db.lock_project(pid1)
    sid = db.create_session("new_project")
    step_id = db.add_step(sid, "Build API", "Build the REST API", 1)
    step = db.get_step(step_id)
    assert step is not None
    # Session belongs to pid1
    sess = db.get_session(sid)
    assert sess["project_id"] == pid1


def test_read_cross_project(db):
    pid1 = db.create_project("app1", "/tmp/app1", "pytest", "", "pytest", "features/")
    pid2 = db.create_project("app2", "/tmp/app2", "pytest", "", "pytest", "features/")
    db.lock_project(pid1)
    db.create_session("new_project")
    # Can list all projects (cross-project read)
    projects = db.list_projects()
    assert len(projects) == 2
    # Can list sessions filtering by project
    db.lock_project(pid2)
    db.create_session("new_feature")
    all_sessions = db.list_sessions()
    assert len(all_sessions) == 2
    p1_sessions = db.list_sessions(project_id=pid1)
    assert len(p1_sessions) == 1


def test_add_step(db):
    pid = db.create_project("myapp", "/tmp/myapp", "pytest", "", "pytest", "features/")
    db.lock_project(pid)
    sid = db.create_session("new_project")
    step_id = db.add_step(sid, "Build API", "Create REST endpoints", 1,
                          feature_path="features/api.feature", gate="tests_only")
    step = db.get_step(step_id)
    assert step["title"] == "Build API"
    assert step["status"] == "pending"
    assert step["gate"] == "tests_only"
    assert step["feature_path"] == "features/api.feature"
    assert step["retries"] == 0


def test_add_test_run(db):
    pid = db.create_project("myapp", "/tmp/myapp", "pytest", "", "pytest", "features/")
    db.lock_project(pid)
    sid = db.create_session("new_project")
    step_id = db.add_step(sid, "Build API", "Create REST endpoints", 1)
    run_id = db.add_test_run(step_id, sid, passed=5, failed=2, coverage=71.5,
                             runner_output="5 passed, 2 failed")
    run = db.get_test_run(run_id)
    assert run["passed"] == 5
    assert run["failed"] == 2
    assert run["coverage"] == 71.5
    latest = db.get_latest_test_run(step_id)
    assert latest["id"] == run_id


def test_add_event(db):
    pid = db.create_project("myapp", "/tmp/myapp", "pytest", "", "pytest", "features/")
    db.lock_project(pid)
    sid = db.create_session("new_project")
    step_id = db.add_step(sid, "Build API", "Create REST endpoints", 1)
    ev_id = db.add_event(sid, "step_started", step_id=step_id, data={"info": "starting"})
    events = db.list_events(sid)
    assert len(events) == 1
    assert events[0]["event_type"] == "step_started"
    assert events[0]["step_id"] == step_id


def test_step_feature_content_and_hash_roundtrip():
    db = Storage(db_path=":memory:")
    pid = db.create_project(name="p", path="/tmp/p")
    db.lock_project(pid)
    sid = db.create_session("new_feature")
    step_id = db.add_step(sid, "S1", "d", 1)
    db.update_step(step_id, feature_content="Feature: X\n", feature_hash="abc123")
    step = db.get_step(step_id)
    assert step["feature_content"] == "Feature: X\n"
    assert step["feature_hash"] == "abc123"
    db.close()


def test_migration_v1_to_v2_adds_feature_columns(tmp_path):
    """A v1 database opened by the new Storage gains the new columns."""
    import sqlite3
    db_file = str(tmp_path / "old.db")
    conn = sqlite3.connect(db_file)
    conn.executescript("""
        CREATE TABLE schema_version (version INTEGER NOT NULL);
        INSERT INTO schema_version (version) VALUES (1);
        CREATE TABLE projects (
            id TEXT PRIMARY KEY, name TEXT NOT NULL, path TEXT NOT NULL UNIQUE,
            test_runner TEXT NOT NULL DEFAULT 'generic', test_args TEXT NOT NULL DEFAULT '',
            adapter TEXT NOT NULL DEFAULT 'generic', features_dir TEXT NOT NULL DEFAULT 'features/',
            created_at REAL NOT NULL);
        CREATE TABLE sessions (
            id TEXT PRIMARY KEY, project_id TEXT NOT NULL REFERENCES projects(id),
            workflow_type TEXT NOT NULL, status TEXT NOT NULL DEFAULT 'active',
            default_rules TEXT, created_at REAL NOT NULL);
        CREATE TABLE steps (
            id TEXT PRIMARY KEY, session_id TEXT NOT NULL REFERENCES sessions(id),
            title TEXT NOT NULL, description TEXT NOT NULL DEFAULT '',
            "order" INTEGER NOT NULL, feature_path TEXT,
            gate TEXT NOT NULL DEFAULT 'tests_only', depends_on TEXT, rules_override TEXT,
            status TEXT NOT NULL DEFAULT 'pending', retries INTEGER NOT NULL DEFAULT 0,
            current_coverage REAL NOT NULL DEFAULT 0.0, gate_result TEXT, created_at REAL NOT NULL);
        CREATE TABLE test_runs (
            id TEXT PRIMARY KEY, step_id TEXT NOT NULL REFERENCES steps(id),
            session_id TEXT NOT NULL REFERENCES sessions(id), run_at REAL NOT NULL,
            passed INTEGER NOT NULL DEFAULT 0, failed INTEGER NOT NULL DEFAULT 0,
            coverage REAL NOT NULL DEFAULT 0.0, runner_output TEXT NOT NULL DEFAULT '');
        CREATE TABLE events (
            id TEXT PRIMARY KEY, session_id TEXT NOT NULL REFERENCES sessions(id),
            event_type TEXT NOT NULL, step_id TEXT, data TEXT, timestamp REAL NOT NULL);
    """)
    conn.commit()
    conn.close()

    db = Storage(db_path=db_file)
    cols = [r[1] for r in db.conn.execute("PRAGMA table_info(steps)").fetchall()]
    assert "feature_content" in cols
    assert "feature_hash" in cols
    ver = db.conn.execute("SELECT version FROM schema_version").fetchone()[0]
    assert ver == 2
    db.close()
