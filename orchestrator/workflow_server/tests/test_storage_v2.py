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
