"""
Shared fixtures for BissetMCP Gherkin tests.

- workflow_client: FastAPI TestClient for workflow_server (no real server needed)
- mcp_session: async MCP ClientSession over subprocess STDIO (for mcp_server_stdio tests)
"""
import os
import pytest
import threading
import uvicorn
from fastapi.testclient import TestClient

DB = '/tmp/bdd_workflow.db'


def _make_app(db_path=DB):
    """Create a fresh workflow_server app with an isolated DB."""
    try:
        os.remove(db_path)
    except FileNotFoundError:
        pass
    import orchestrator.workflow_server.app as app_module
    from orchestrator.workflow_server.storage import Storage
    from orchestrator.workflow_server.catalog import Catalog
    from orchestrator.workflow_server.renderers import Renderers
    from orchestrator.workflow_server.engine import WorkflowEngine
    storage = Storage(db_path)
    catalog = Catalog()
    renderers = Renderers(storage)
    engine = WorkflowEngine(storage, catalog, renderers)
    app_module._storage = storage
    app_module._catalog = catalog
    app_module._renderers = renderers
    app_module._engine = engine
    return app_module.app, storage, engine


@pytest.fixture
def workflow_client():
    """Fresh TestClient for each test."""
    app, storage, engine = _make_app()
    with TestClient(app) as client:
        yield client
    try:
        os.remove(DB)
    except FileNotFoundError:
        pass


@pytest.fixture
def started_client(workflow_client):
    """TestClient with a workflow already started (includes project_path)."""
    workflow_client.post('/tools/workflow_new_session', json={'arguments': {'name': 'TestProject'}})
    workflow_client.post('/tools/workflow_start', json={'arguments': {'project_meta': {'name': 'TestProject', 'project_path': '/tmp/test_project', 'test_runner': 'echo ok'}}})
    return workflow_client


@pytest.fixture
def answered_client(started_client):
    """TestClient with all questions answered."""
    from orchestrator.workflow_server.catalog import QUESTIONS
    for qid, _ in QUESTIONS:
        started_client.post('/tools/workflow_record_answer', json={
            'arguments': {'question_id': qid, 'answer_text': f'answer for {qid}'}
        })
    return started_client


@pytest.fixture
def frozen_client(answered_client):
    """TestClient with spec frozen (execution phase)."""
    answered_client.post('/tools/workflow_freeze_spec', json={'arguments': {}})
    return answered_client


def _answer_all(client):
    from orchestrator.workflow_server.catalog import QUESTIONS
    for qid, _ in QUESTIONS:
        client.post('/tools/workflow_record_answer', json={
            'arguments': {'question_id': qid, 'answer_text': f'answer for {qid}'}
        })


def _accept_all(client):
    from orchestrator.workflow_server.catalog import PLAN_TASKS
    for tid, _ in PLAN_TASKS:
        client.post('/tools/workflow_accept_task_result', json={'arguments': {
            'task_id': tid, 'summary': 'done',
            'artifacts_changed': [], 'tests_run': [], 'test_results': {}
        }})
