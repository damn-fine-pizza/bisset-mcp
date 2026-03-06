"""Tests for Bisset v2 Workflow Engine."""
import pytest
from orchestrator.workflow_server.storage import Storage
from orchestrator.workflow_server.engine import WorkflowEngine


DEFAULT_RULES = [
    {"when": "tests_pass AND coverage >= 80", "then": "advance"},
    {"when": "tests_fail AND retries < 3", "then": "retry"},
    {"when": "tests_fail AND retries >= 3", "then": "ask_user"},
    {"when": "no_tests", "then": "ask_user"},
    {"when": "always", "then": "abort"},
]


@pytest.fixture
def engine():
    db = Storage(db_path=":memory:")
    eng = WorkflowEngine(db)
    yield eng
    db.close()


def test_create_project_and_session(engine):
    pid = engine.create_project("myapp", "/tmp/myapp", test_runner="pytest", adapter="pytest")
    assert pid is not None
    sid = engine.start_session(pid, "new_project", default_rules=DEFAULT_RULES)
    assert sid is not None
    status = engine.session_status(sid)
    assert status["session"]["status"] == "active"
    assert status["session"]["workflow_type"] == "new_project"


def test_add_steps_and_get_current(engine):
    pid = engine.create_project("myapp", "/tmp/myapp")
    sid = engine.start_session(pid, "new_project", default_rules=DEFAULT_RULES)
    engine.add_step(sid, "Step 1", "First step", 1)
    engine.add_step(sid, "Step 2", "Second step", 2)
    current = engine.current_step(sid)
    assert current is not None
    assert current["title"] == "Step 1"


def test_step_complete_advance(engine):
    pid = engine.create_project("myapp", "/tmp/myapp")
    sid = engine.start_session(pid, "new_project", default_rules=DEFAULT_RULES)
    step_id = engine.add_step(sid, "Step 1", "First step", 1)
    engine.add_step(sid, "Step 2", "Second step", 2)
    # Record a passing test run
    engine.record_test_run(step_id, sid, passed=5, failed=0, coverage=90.0)
    action = engine.complete_step(step_id, sid)
    assert action == "advance"
    # Step 1 should now be passed
    step = engine.db.get_step(step_id)
    assert step["status"] == "passed"


def test_step_complete_retry(engine):
    pid = engine.create_project("myapp", "/tmp/myapp")
    sid = engine.start_session(pid, "new_project", default_rules=DEFAULT_RULES)
    step_id = engine.add_step(sid, "Step 1", "First step", 1)
    # Record a failing test run
    engine.record_test_run(step_id, sid, passed=3, failed=2, coverage=60.0)
    action = engine.complete_step(step_id, sid)
    assert action == "retry"
    step = engine.db.get_step(step_id)
    assert step["status"] == "active"
    assert step["retries"] == 1


def test_step_complete_ask_user_after_retries(engine):
    pid = engine.create_project("myapp", "/tmp/myapp")
    sid = engine.start_session(pid, "new_project", default_rules=DEFAULT_RULES)
    step_id = engine.add_step(sid, "Step 1", "First step", 1)
    # Set retries to 3
    engine.db.update_step(step_id, retries=3)
    engine.record_test_run(step_id, sid, passed=3, failed=2, coverage=60.0)
    action = engine.complete_step(step_id, sid)
    assert action == "ask_user"


def test_session_resume(engine):
    pid = engine.create_project("myapp", "/tmp/myapp")
    sid = engine.start_session(pid, "new_project", default_rules=DEFAULT_RULES)
    step_id = engine.add_step(sid, "Step 1", "First step", 1)
    # Pause session
    engine.db.update_session_status(sid, "paused")
    # Resume
    resumed_sid = engine.resume_session(pid)
    assert resumed_sid == sid
    sess = engine.db.get_session(resumed_sid)
    assert sess["status"] == "active"


def test_project_lock_isolation(engine):
    pid1 = engine.create_project("app1", "/tmp/app1")
    pid2 = engine.create_project("app2", "/tmp/app2")
    sid1 = engine.start_session(pid1, "new_project", default_rules=DEFAULT_RULES)
    sid2 = engine.start_session(pid2, "new_feature", default_rules=DEFAULT_RULES)
    # Sessions belong to different projects
    s1 = engine.db.get_session(sid1)
    s2 = engine.db.get_session(sid2)
    assert s1["project_id"] == pid1
    assert s2["project_id"] == pid2
