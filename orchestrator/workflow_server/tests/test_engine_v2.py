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


def test_default_rules_green_tests_advance(engine):
    """A session created without rules must use sane defaults: green tests advance."""
    pid = engine.create_project("myapp", "/tmp/myapp")
    sid = engine.start_session(pid, "new_project")  # no default_rules
    step_id = engine.add_step(sid, "Step 1", "First step", 1)
    engine.record_test_run(step_id, sid, passed=2, failed=0, coverage=0.0)
    action = engine.complete_step(step_id, sid)
    assert action == "advance"
    assert engine.db.get_step(step_id)["status"] == "passed"


def test_default_rules_red_tests_retry(engine):
    """Without session rules, failing tests must retry — never advance."""
    pid = engine.create_project("myapp", "/tmp/myapp")
    sid = engine.start_session(pid, "new_project")
    step_id = engine.add_step(sid, "Step 1", "First step", 1)
    engine.record_test_run(step_id, sid, passed=1, failed=1, coverage=50.0)
    action = engine.complete_step(step_id, sid)
    assert action == "retry"
    assert engine.db.get_step(step_id)["status"] == "active"


def test_default_rules_red_tests_exhausted_retries_ask_user(engine):
    pid = engine.create_project("myapp", "/tmp/myapp")
    sid = engine.start_session(pid, "new_project")
    step_id = engine.add_step(sid, "Step 1", "First step", 1)
    engine.db.update_step(step_id, retries=3)
    engine.record_test_run(step_id, sid, passed=1, failed=1, coverage=50.0)
    action = engine.complete_step(step_id, sid)
    assert action == "ask_user"


def test_default_rules_human_gate_asks_user_even_when_green(engine):
    pid = engine.create_project("myapp", "/tmp/myapp")
    sid = engine.start_session(pid, "new_project")
    step_id = engine.add_step(sid, "Step 1", "First step", 1, gate="human_approval")
    engine.record_test_run(step_id, sid, passed=2, failed=0, coverage=100.0)
    action = engine.complete_step(step_id, sid)
    assert action == "ask_user"


def test_default_rules_no_tests_ask_user(engine):
    pid = engine.create_project("myapp", "/tmp/myapp")
    sid = engine.start_session(pid, "new_project")
    step_id = engine.add_step(sid, "Step 1", "First step", 1)
    action = engine.complete_step(step_id, sid)
    assert action == "ask_user"


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


VALID_FEATURE = """Feature: Calculator
  Scenario: Add
    Given the numbers 1 and 2
    When I add them
    Then the result is 3
"""


def test_set_feature_writes_file_and_registers(engine, tmp_path):
    pid = engine.create_project("myapp", str(tmp_path), adapter="behave")
    sid = engine.start_session(pid, "new_feature")
    step_id = engine.add_step(sid, "Implement calculator", "d", 1)

    result = engine.set_feature(step_id, sid, VALID_FEATURE)
    assert result["written"] is True
    assert result["feature_path"] == "features/implement-calculator.feature"

    written = (tmp_path / "features" / "implement-calculator.feature").read_text()
    assert written == VALID_FEATURE

    step = engine.db.get_step(step_id)
    assert step["feature_path"] == "features/implement-calculator.feature"
    assert step["feature_content"] == VALID_FEATURE
    assert len(step["feature_hash"]) == 64  # sha256 hex

    events = engine.db.list_events(sid)
    assert any(e["event_type"] == "feature_set" for e in events)


def test_set_feature_rejects_bad_syntax_without_writing(engine, tmp_path):
    pid = engine.create_project("myapp", str(tmp_path), adapter="behave")
    sid = engine.start_session(pid, "new_feature")
    step_id = engine.add_step(sid, "Bad", "d", 1)

    result = engine.set_feature(step_id, sid, "this is not gherkin at all")
    assert result["written"] is False
    assert result["errors"]
    assert not (tmp_path / "features").exists()
    assert engine.db.get_step(step_id)["feature_content"] is None


def test_set_feature_rejects_traversal_filename(engine, tmp_path):
    pid = engine.create_project("myapp", str(tmp_path), adapter="behave")
    sid = engine.start_session(pid, "new_feature")
    step_id = engine.add_step(sid, "S", "d", 1)
    with pytest.raises(ValueError):
        engine.set_feature(step_id, sid, VALID_FEATURE, filename="../evil")


def test_set_feature_unknown_session_raises(engine, tmp_path):
    pid = engine.create_project("myapp", str(tmp_path), adapter="behave")
    sid = engine.start_session(pid, "new_feature")
    step_id = engine.add_step(sid, "S", "d", 1)
    with pytest.raises(ValueError, match="Session not found"):
        engine.set_feature(step_id, "nonexistent", VALID_FEATURE)


def test_set_feature_explicit_filename(engine, tmp_path):
    pid = engine.create_project("myapp", str(tmp_path), adapter="behave")
    sid = engine.start_session(pid, "new_feature")
    step_id = engine.add_step(sid, "S", "d", 1)
    result = engine.set_feature(step_id, sid, VALID_FEATURE, filename="my_calc")
    assert result["feature_path"] == "features/my_calc.feature"
    assert (tmp_path / "features" / "my_calc.feature").exists()


def test_set_feature_overwrites_and_updates_hash(engine, tmp_path):
    pid = engine.create_project("myapp", str(tmp_path), adapter="behave")
    sid = engine.start_session(pid, "new_feature")
    step_id = engine.add_step(sid, "Calc", "d", 1)
    first = engine.set_feature(step_id, sid, VALID_FEATURE)
    updated = VALID_FEATURE + "\n  Scenario: More\n    Given more\n"
    second = engine.set_feature(step_id, sid, updated)
    assert second["hash"] != first["hash"]
    assert (tmp_path / "features" / "calc.feature").read_text() == updated
    assert engine.db.get_step(step_id)["feature_content"] == updated


def test_get_feature_no_drift(engine, tmp_path):
    pid = engine.create_project("myapp", str(tmp_path), adapter="behave")
    sid = engine.start_session(pid, "new_feature")
    step_id = engine.add_step(sid, "Calc", "d", 1)
    engine.set_feature(step_id, sid, VALID_FEATURE)

    result = engine.get_feature(step_id, sid)
    assert result["content"] == VALID_FEATURE
    assert result["feature_drifted"] is False
    assert result["file_missing"] is False


def test_get_feature_detects_drift_and_realigns(engine, tmp_path):
    pid = engine.create_project("myapp", str(tmp_path), adapter="behave")
    sid = engine.start_session(pid, "new_feature")
    step_id = engine.add_step(sid, "Calc", "d", 1)
    engine.set_feature(step_id, sid, VALID_FEATURE)

    edited = VALID_FEATURE + "\n  Scenario: Human added\n    Given x\n"
    (tmp_path / "features" / "calc.feature").write_text(edited)

    result = engine.get_feature(step_id, sid)
    assert result["feature_drifted"] is True
    assert result["content"] == edited
    # DB copy realigned, event logged
    assert engine.db.get_step(step_id)["feature_content"] == edited
    events = engine.db.list_events(sid)
    assert any(e["event_type"] == "feature_drift" for e in events)
    # Second read: no longer drifted
    assert engine.get_feature(step_id, sid)["feature_drifted"] is False


def test_get_feature_file_missing_returns_db_copy(engine, tmp_path):
    pid = engine.create_project("myapp", str(tmp_path), adapter="behave")
    sid = engine.start_session(pid, "new_feature")
    step_id = engine.add_step(sid, "Calc", "d", 1)
    engine.set_feature(step_id, sid, VALID_FEATURE)
    (tmp_path / "features" / "calc.feature").unlink()

    result = engine.get_feature(step_id, sid)
    assert result["file_missing"] is True
    assert result["content"] == VALID_FEATURE  # last DB copy as reference


def test_run_tests_reports_drift(engine, tmp_path):
    """run_tests flags drift when the file changed after set_feature.

    Uses the 'generic' runner with /bin/true so no real test framework runs.
    """
    pid = engine.create_project("myapp", str(tmp_path),
                                test_runner="true", adapter="generic")
    sid = engine.start_session(pid, "new_feature")
    step_id = engine.add_step(sid, "Calc", "d", 1)
    engine.set_feature(step_id, sid, VALID_FEATURE)

    (tmp_path / "features" / "calc.feature").write_text(VALID_FEATURE + "# edited\n")

    result, drifted = engine.run_tests(step_id, sid)
    assert drifted is True
    assert result.passed == 1  # /bin/true exit 0 -> generic adapter pass

    # second run: realigned, no drift
    result, drifted = engine.run_tests(step_id, sid)
    assert drifted is False


import os as _os

BEHAVE = _os.path.join(_os.path.dirname(__file__), "..", "..", "..", ".venv", "bin", "behave")
BEHAVE = _os.path.abspath(BEHAVE)

STEPS_PY = '''
from behave import given, when, then

@given("the numbers {a:d} and {b:d}")
def step_given(ctx, a, b):
    ctx.a, ctx.b = a, b

@when("I add them")
def step_when(ctx):
    ctx.result = ctx.a + ctx.b

@then("the result is {expected:d}")
def step_then(ctx, expected):
    assert ctx.result == expected
'''


def _behave_project(engine, tmp_path):
    pid = engine.create_project("myapp", str(tmp_path),
                                test_runner=BEHAVE,
                                test_args="--format json --no-snippets",
                                adapter="behave")
    sid = engine.start_session(pid, "new_feature")
    step_id = engine.add_step(sid, "Calc", "d", 1)
    steps_dir = tmp_path / "features" / "steps"
    steps_dir.mkdir(parents=True)
    (steps_dir / "calc_steps.py").write_text(STEPS_PY)
    return sid, step_id


@pytest.mark.skipif(not _os.path.exists(BEHAVE), reason="behave not installed in .venv")
def test_validate_feature_all_defined(engine, tmp_path):
    sid, step_id = _behave_project(engine, tmp_path)
    engine.set_feature(step_id, sid, VALID_FEATURE)
    v = engine.validate_feature(step_id, sid)
    assert v["syntax_ok"] is True
    assert v["steps_defined"] is True
    assert v["undefined_steps"] == []
    assert v["errors"] == []


@pytest.mark.skipif(not _os.path.exists(BEHAVE), reason="behave not installed in .venv")
def test_validate_feature_undefined_step(engine, tmp_path):
    sid, step_id = _behave_project(engine, tmp_path)
    feature = VALID_FEATURE + "\n  Scenario: Ghost\n    Given a step nobody wrote\n"
    engine.set_feature(step_id, sid, feature)
    v = engine.validate_feature(step_id, sid)
    assert v["syntax_ok"] is True
    assert v["steps_defined"] is False
    assert any("a step nobody wrote" in s for s in v["undefined_steps"])


@pytest.mark.skipif(not _os.path.exists(BEHAVE), reason="behave not installed in .venv")
def test_validate_feature_broken_gherkin(engine, tmp_path):
    sid, step_id = _behave_project(engine, tmp_path)
    # bypass set_feature's structural check: write broken file directly
    engine.set_feature(step_id, sid, VALID_FEATURE)
    (tmp_path / "features" / "calc.feature").write_text(
        "Feature: X\n  Scenario: bad\n    Given ok\n  Garbage line outside any step\n")
    v = engine.validate_feature(step_id, sid)
    # behave refuses to parse -> syntax_ok False, errors carry the parser output
    assert v["syntax_ok"] is False
    assert v["errors"]


def test_validate_feature_requires_behave_adapter(engine, tmp_path):
    pid = engine.create_project("p", str(tmp_path), adapter="pytest")
    sid = engine.start_session(pid, "new_feature")
    step_id = engine.add_step(sid, "S", "d", 1, feature_path="x.feature")
    with pytest.raises(ValueError):
        engine.validate_feature(step_id, sid)
