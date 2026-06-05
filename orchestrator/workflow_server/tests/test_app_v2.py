"""Tests for Bisset v2 FastAPI Endpoints."""
import json

import pytest
from fastapi.testclient import TestClient
from orchestrator.workflow_server.app import app, _override_db_path


@pytest.fixture
def client():
    _override_db_path(":memory:")
    with TestClient(app) as c:
        yield c
    _override_db_path(None)


def test_health(client):
    r = client.get("/health")
    assert r.status_code == 200
    assert r.json()["status"] == "healthy"


def test_project_create(client):
    r = client.post("/project_create", json={
        "name": "myapp",
        "path": "/tmp/myapp",
        "test_runner": "pytest",
        "adapter": "pytest",
    })
    assert r.status_code == 200
    data = r.json()
    assert data["is_error"] is False
    payload = json.loads(data["content"][0]["text"])
    assert "project_id" in payload


def test_session_start(client):
    # Create project first
    r1 = client.post("/project_create", json={
        "name": "myapp", "path": "/tmp/myapp2",
    })
    pid = json.loads(r1.json()["content"][0]["text"])["project_id"]

    # Start session
    r2 = client.post("/session_start", json={
        "project_id": pid,
        "workflow_type": "new_project",
    })
    assert r2.status_code == 200
    data = r2.json()
    assert data["is_error"] is False
    payload = json.loads(data["content"][0]["text"])
    assert "session_id" in payload


def test_pipeline_view(client):
    # Create project + session + steps
    r1 = client.post("/project_create", json={
        "name": "myapp", "path": "/tmp/myapp3",
    })
    pid = json.loads(r1.json()["content"][0]["text"])["project_id"]

    r2 = client.post("/session_start", json={
        "project_id": pid, "workflow_type": "new_project",
    })
    sid = json.loads(r2.json()["content"][0]["text"])["session_id"]

    # Add steps
    client.post("/step_add", json={
        "session_id": sid, "title": "Step 1", "description": "First", "order": 1,
    })
    client.post("/step_add", json={
        "session_id": sid, "title": "Step 2", "description": "Second", "order": 2,
    })

    # Get pipeline view
    r3 = client.get(f"/pipeline_view?session_id={sid}")
    assert r3.status_code == 200
    data = r3.json()
    payload = json.loads(data["content"][0]["text"])
    assert payload["total_steps"] == 2


def test_step_current(client):
    r1 = client.post("/project_create", json={
        "name": "myapp", "path": "/tmp/myapp4",
    })
    pid = json.loads(r1.json()["content"][0]["text"])["project_id"]

    r2 = client.post("/session_start", json={
        "project_id": pid, "workflow_type": "new_project",
    })
    sid = json.loads(r2.json()["content"][0]["text"])["session_id"]

    client.post("/step_add", json={
        "session_id": sid, "title": "Step 1", "description": "Do it", "order": 1,
    })

    r3 = client.get(f"/step_current?session_id={sid}")
    assert r3.status_code == 200
    data = r3.json()
    assert data["is_error"] is False
    payload = json.loads(data["content"][0]["text"])
    assert payload["title"] == "Step 1"


def test_step_skip(client):
    r1 = client.post("/project_create", json={
        "name": "myapp", "path": "/tmp/myapp5",
    })
    pid = json.loads(r1.json()["content"][0]["text"])["project_id"]

    r2 = client.post("/session_start", json={
        "project_id": pid, "workflow_type": "new_project",
    })
    sid = json.loads(r2.json()["content"][0]["text"])["session_id"]

    r3 = client.post("/step_add", json={
        "session_id": sid, "title": "Step 1", "description": "Do it", "order": 1,
    })
    step_id = json.loads(r3.json()["content"][0]["text"])["step_id"]

    r4 = client.post("/step_skip", json={
        "step_id": step_id, "session_id": sid, "reason": "Not needed",
    })
    assert r4.status_code == 200
    assert r4.json()["is_error"] is False


def test_session_status(client):
    r1 = client.post("/project_create", json={
        "name": "myapp", "path": "/tmp/myapp6",
    })
    pid = json.loads(r1.json()["content"][0]["text"])["project_id"]

    r2 = client.post("/session_start", json={
        "project_id": pid, "workflow_type": "new_project",
    })
    sid = json.loads(r2.json()["content"][0]["text"])["session_id"]

    r3 = client.get(f"/session_status?session_id={sid}")
    assert r3.status_code == 200
    data = r3.json()
    assert data["is_error"] is False
    payload = json.loads(data["content"][0]["text"])
    assert payload["session"]["status"] == "active"


def test_project_list(client):
    client.post("/project_create", json={
        "name": "app1", "path": "/tmp/app1",
    })
    client.post("/project_create", json={
        "name": "app2", "path": "/tmp/app2",
    })

    r = client.get("/project_list")
    assert r.status_code == 200
    data = r.json()
    payload = json.loads(data["content"][0]["text"])
    assert len(payload["projects"]) == 2


def test_event_log(client):
    r1 = client.post("/project_create", json={
        "name": "myapp", "path": "/tmp/myapp7",
    })
    pid = json.loads(r1.json()["content"][0]["text"])["project_id"]

    r2 = client.post("/session_start", json={
        "project_id": pid, "workflow_type": "new_project",
    })
    sid = json.loads(r2.json()["content"][0]["text"])["session_id"]

    r3 = client.get(f"/event_log?session_id={sid}")
    assert r3.status_code == 200
    data = r3.json()
    payload = json.loads(data["content"][0]["text"])
    # session_started event should be there
    assert len(payload["events"]) >= 1


def test_step_list(client):
    r1 = client.post("/project_create", json={
        "name": "myapp", "path": "/tmp/myapp8",
    })
    pid = json.loads(r1.json()["content"][0]["text"])["project_id"]

    r2 = client.post("/session_start", json={
        "project_id": pid, "workflow_type": "new_project",
    })
    sid = json.loads(r2.json()["content"][0]["text"])["session_id"]

    client.post("/step_add", json={
        "session_id": sid, "title": "A", "description": "a", "order": 1,
    })
    client.post("/step_add", json={
        "session_id": sid, "title": "B", "description": "b", "order": 2,
    })

    r3 = client.get(f"/step_list?session_id={sid}")
    assert r3.status_code == 200
    payload = json.loads(r3.json()["content"][0]["text"])
    assert len(payload["steps"]) == 2


def _payload(response):
    """Extract payload dict from ResponseWrapper response."""
    return json.loads(response.json()["content"][0]["text"])


VALID_FEATURE = """Feature: Calculator
  Scenario: Add
    Given the numbers 1 and 2
    When I add them
    Then the result is 3
"""


def test_step_set_and_get_feature_endpoints(client, tmp_path):
    r = client.post("/project_create", json={
        "name": "gf-app", "path": str(tmp_path), "adapter": "behave",
    })
    pid = _payload(r)["project_id"]
    r = client.post("/session_start", json={"project_id": pid, "workflow_type": "new_feature"})
    sid = _payload(r)["session_id"]
    r = client.post("/step_add", json={"session_id": sid, "title": "Calc", "order": 1})
    step_id = _payload(r)["step_id"]

    r = client.post("/step_set_feature", json={
        "step_id": step_id, "session_id": sid, "content": VALID_FEATURE,
    })
    assert r.status_code == 200
    body = _payload(r)
    assert body["written"] is True
    assert body["feature_path"] == "features/calc.feature"

    r = client.get(f"/step_get_feature?step_id={step_id}&session_id={sid}")
    body = _payload(r)
    assert body["content"] == VALID_FEATURE
    assert body["feature_drifted"] is False


def test_step_set_feature_rejects_bad_gherkin(client, tmp_path):
    r = client.post("/project_create", json={
        "name": "gf-bad", "path": str(tmp_path), "adapter": "behave",
    })
    pid = _payload(r)["project_id"]
    r = client.post("/session_start", json={"project_id": pid, "workflow_type": "new_feature"})
    sid = _payload(r)["session_id"]
    r = client.post("/step_add", json={"session_id": sid, "title": "Bad", "order": 1})
    step_id = _payload(r)["step_id"]

    r = client.post("/step_set_feature", json={
        "step_id": step_id, "session_id": sid, "content": "garbage",
    })
    body = _payload(r)
    assert body["written"] is False
    assert body["errors"]


def test_step_run_tests_reports_feature_drifted(client, tmp_path):
    r = client.post("/project_create", json={
        "name": "drift-app", "path": str(tmp_path),
        "test_runner": "true", "adapter": "generic",
    })
    pid = _payload(r)["project_id"]
    r = client.post("/session_start", json={"project_id": pid, "workflow_type": "new_feature"})
    sid = _payload(r)["session_id"]
    r = client.post("/step_add", json={"session_id": sid, "title": "Calc", "order": 1})
    step_id = _payload(r)["step_id"]
    r = client.post("/step_set_feature", json={
        "step_id": step_id, "session_id": sid, "content": VALID_FEATURE,
    })
    assert _payload(r)["written"] is True

    (tmp_path / "features" / "calc.feature").write_text(VALID_FEATURE + "# edited\n")
    r = client.post("/step_run_tests", json={"step_id": step_id, "session_id": sid})
    body = _payload(r)
    assert body["feature_drifted"] is True
    assert body["passed"] == 1  # /bin/true via generic adapter


def test_step_validate_feature_requires_behave(client, tmp_path):
    r = client.post("/project_create", json={
        "name": "val-app", "path": str(tmp_path), "adapter": "pytest",
    })
    pid = _payload(r)["project_id"]
    r = client.post("/session_start", json={"project_id": pid, "workflow_type": "new_feature"})
    sid = _payload(r)["session_id"]
    r = client.post("/step_add", json={"session_id": sid, "title": "S", "order": 1})
    step_id = _payload(r)["step_id"]
    r = client.post("/step_set_feature", json={
        "step_id": step_id, "session_id": sid, "content": VALID_FEATURE,
    })
    r = client.get(f"/step_validate_feature?step_id={step_id}&session_id={sid}")
    data = r.json()
    assert data["is_error"] is True  # behave adapter required
