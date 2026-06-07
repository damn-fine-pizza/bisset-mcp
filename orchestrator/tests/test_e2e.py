"""End-to-end integration test for Bisset v2 full pipeline lifecycle."""
import json
import pytest
from fastapi.testclient import TestClient
from orchestrator.workflow_server.app import app, _override_db_path


DEFAULT_RULES = [
    {"when": "tests_pass AND coverage >= 80", "then": "advance"},
    {"when": "tests_fail AND retries < 3", "then": "retry"},
    {"when": "tests_fail AND retries >= 3", "then": "ask_user"},
    {"when": "no_tests", "then": "ask_user"},
    {"when": "always", "then": "abort"},
]


def _payload(response):
    """Extract payload dict from ResponseWrapper response."""
    data = response.json()
    return json.loads(data["content"][0]["text"])


@pytest.fixture
def client():
    _override_db_path(":memory:")
    with TestClient(app) as c:
        yield c
    _override_db_path(None)


def test_full_pipeline_lifecycle(client):
    """Full lifecycle: create project -> start session -> add steps ->
    record test runs -> complete steps -> verify session completed."""

    # 1. Create project
    r = client.post("/project_create", json={
        "name": "e2e-app",
        "path": "/tmp/e2e-app",
        "test_runner": "pytest",
        "adapter": "pytest",
    })
    assert r.status_code == 200
    pid = _payload(r)["project_id"]

    # 2. Start session with rules
    r = client.post("/session_start", json={
        "project_id": pid,
        "workflow_type": "new_project",
        "default_rules": DEFAULT_RULES,
    })
    assert r.status_code == 200
    sid = _payload(r)["session_id"]

    # 3. Add steps
    r = client.post("/step_add", json={
        "session_id": sid, "title": "Setup DB", "description": "Create database schema", "order": 1,
    })
    step1_id = _payload(r)["step_id"]

    r = client.post("/step_add", json={
        "session_id": sid, "title": "Build API", "description": "REST endpoints", "order": 2,
    })
    step2_id = _payload(r)["step_id"]

    # 4. Verify pipeline view
    r = client.get(f"/pipeline_view?session_id={sid}")
    pipeline = _payload(r)
    assert pipeline["total_steps"] == 2
    assert pipeline["completed_steps"] == 0

    # 5. Get current step (should be step 1)
    r = client.get(f"/step_current?session_id={sid}")
    current = _payload(r)
    assert current["title"] == "Setup DB"

    # 6. Record passing test run for step 1, then complete
    # First, we need to record test results via the engine directly
    # (step_run_tests would need a real subprocess, so we record manually)
    # Use the engine's record_test_run via a direct DB operation
    engine = client.app.state.engine
    engine.record_test_run(step1_id, sid, passed=5, failed=0, coverage=95.0)

    r = client.post("/step_complete", json={
        "step_id": step1_id, "session_id": sid,
    })
    result = _payload(r)
    assert result["action"] == "advance"

    # 7. Verify step 1 is now passed
    r = client.get(f"/step_list?session_id={sid}")
    steps = _payload(r)["steps"]
    step1 = [s for s in steps if s["id"] == step1_id][0]
    assert step1["status"] == "passed"

    # 8. Step 2: record failing test, should retry
    engine.record_test_run(step2_id, sid, passed=3, failed=2, coverage=60.0)
    r = client.post("/step_complete", json={
        "step_id": step2_id, "session_id": sid,
    })
    assert _payload(r)["action"] == "retry"

    # 9. Step 2: record passing test after retry, should advance
    engine.record_test_run(step2_id, sid, passed=5, failed=0, coverage=90.0)
    r = client.post("/step_complete", json={
        "step_id": step2_id, "session_id": sid,
    })
    assert _payload(r)["action"] == "advance"

    # 10. Verify session is completed (all steps passed)
    r = client.get(f"/session_status?session_id={sid}")
    status = _payload(r)
    assert status["session"]["status"] == "completed"
    assert status["completed_steps"] == 2

    # 11. Verify event log has entries
    r = client.get(f"/event_log?session_id={sid}")
    events = _payload(r)["events"]
    assert len(events) > 0
    event_types = {e["event_type"] for e in events}
    assert "session_started" in event_types
    assert "step_completed" in event_types

    # 12. Verify project list
    r = client.get("/project_list")
    projects = _payload(r)["projects"]
    assert len(projects) == 1
    assert projects[0]["name"] == "e2e-app"


def test_gherkin_feature_lifecycle(client, tmp_path):
    """set -> get -> manual edit -> drift reported on read."""
    r = client.post("/project_create", json={
        "name": "gherkin-e2e", "path": str(tmp_path), "adapter": "behave",
    })
    pid = _payload(r)["project_id"]
    r = client.post("/session_start", json={"project_id": pid, "workflow_type": "new_feature"})
    sid = _payload(r)["session_id"]
    r = client.post("/step_add", json={"session_id": sid, "title": "Calc feature", "order": 1})
    step_id = _payload(r)["step_id"]

    feature = "Feature: Calc\n  Scenario: Add\n    Given two numbers\n    When added\n    Then result\n"
    r = client.post("/step_set_feature", json={
        "step_id": step_id, "session_id": sid, "content": feature,
    })
    assert _payload(r)["written"] is True
    path = tmp_path / "features" / "calc-feature.feature"
    assert path.read_text() == feature

    # human edits the spec on disk
    path.write_text(feature + "    And audited\n")
    r = client.get(f"/step_get_feature?step_id={step_id}&session_id={sid}")
    body = _payload(r)
    assert body["feature_drifted"] is True

    # audit trail
    r = client.get(f"/event_log?session_id={sid}")
    types = {e["event_type"] for e in _payload(r)["events"]}
    assert {"feature_set", "feature_drift"} <= types


def test_interview_lifecycle(client):
    """question -> gate blocks step_add -> answer -> complete -> step_add ok
    -> audit trail -> resume reports the interview."""
    r = client.post("/project_create", json={
        "name": "interview-e2e", "path": "/tmp/interview-e2e",
    })
    pid = _payload(r)["project_id"]
    r = client.post("/session_start", json={
        "project_id": pid, "workflow_type": "new_project",
    })
    sid = _payload(r)["session_id"]

    # 1. Claude registers the question before asking it
    r = client.post("/interview_question", json={
        "session_id": sid, "question": "What does the project do?",
    })
    qid = _payload(r)["question_id"]

    # 2. The gate blocks step generation mid-interview
    r = client.post("/step_add", json={"session_id": sid, "title": "S1", "order": 1})
    assert r.json()["is_error"] is True
    assert "What does the project do?" in _payload(r)["error"]

    # 3. Resume mid-interview: the pending question comes back
    r = client.post("/session_resume", json={"project_id": pid})
    body = _payload(r)
    assert body["session_id"] == sid
    assert body["interview"]["pending_question"]["id"] == qid

    # 4. pipeline_view carries the interview block too (additive)
    r = client.get(f"/pipeline_view?session_id={sid}")
    assert _payload(r)["interview"] is not None

    # 5. Answer + complete
    r = client.post("/interview_answer", json={
        "question_id": qid, "answer": "A pizza ordering API",
    })
    assert _payload(r)["revised"] is False
    r = client.post("/interview_complete", json={"session_id": sid})
    assert _payload(r)["asked"] == 1

    # 6. Gate open
    r = client.post("/step_add", json={"session_id": sid, "title": "S1", "order": 1})
    assert r.json()["is_error"] is False

    # 7. Full audit trail
    r = client.get(f"/event_log?session_id={sid}")
    types = {e["event_type"] for e in _payload(r)["events"]}
    assert {"question_asked", "answer_recorded", "interview_completed"} <= types


def test_analysis_lifecycle(client, tmp_path):
    """submit -> gate blocks step_add -> resume reports proposal -> revise
    -> approve -> steps + feature on disk -> step_add ok -> audit trail."""
    r = client.post("/project_create", json={
        "name": "analysis-e2e", "path": str(tmp_path), "adapter": "behave",
    })
    pid = _payload(r)["project_id"]
    r = client.post("/session_start", json={
        "project_id": pid, "workflow_type": "generate_tests",
    })
    sid = _payload(r)["session_id"]

    draft = ("Feature: Health\n"
             "  Scenario: Service is up\n"
             "    Given the API is running\n"
             "    When I GET /health\n"
             "    Then I receive 200\n")

    # 1. Claude submits the analyzed pipeline as a proposal
    r = client.post("/analysis_submit", json={"session_id": sid, "steps": [
        {"title": "Cover health", "feature_draft": draft},
        {"title": "Cover orders", "description": "order flows"},
    ]})
    assert _payload(r)["submitted"] is True

    # 2. The gate blocks manual step_add while the proposal is open
    r = client.post("/step_add", json={"session_id": sid, "title": "S1", "order": 1})
    assert r.json()["is_error"] is True
    assert "analysis_approve" in _payload(r)["error"]

    # 3. Resume mid-proposal: the analysis block comes back
    r = client.post("/session_resume", json={"project_id": pid})
    body = _payload(r)
    assert body["session_id"] == sid
    assert body["analysis"]["status"] == "open"
    assert body["analysis"]["steps_proposed"] == 2

    # 4. Revision: re-submitting replaces the whole list
    r = client.post("/analysis_submit", json={"session_id": sid, "steps": [
        {"title": "Cover health", "feature_draft": draft},
    ]})
    assert _payload(r)["revised"] is True

    # 5. Approval materializes: real step + feature file on disk
    r = client.post("/analysis_approve", json={"session_id": sid})
    body = _payload(r)
    assert body["steps_created"] == 1
    assert body["features_written"] == 1
    assert (tmp_path / "features" / "01-cover-health.feature").read_text() == draft

    # 6. Gate open again
    r = client.post("/step_add", json={"session_id": sid, "title": "Manual", "order": 99})
    assert r.json()["is_error"] is False

    # 7. Full audit trail
    r = client.get(f"/event_log?session_id={sid}")
    types = {e["event_type"] for e in _payload(r)["events"]}
    assert {"analysis_submitted", "analysis_revised", "analysis_approved",
            "step_added", "feature_set"} <= types
