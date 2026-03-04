import os
import pytest
from pytest_bdd import scenarios, given, when, then, parsers
from .conftest import _make_app, DB
from fastapi.testclient import TestClient

scenarios('../backend_reload.feature')

_DB_RELOAD = '/tmp/bdd_reload.db'


def _fresh_client(db_path=_DB_RELOAD):
    app, storage, engine = _make_app(db_path)
    return TestClient(app), storage, engine


def _reconnect_client(db_path):
    """Create a new app instance reusing an existing DB (simulates restart)."""
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
    return TestClient(app_module.app)


@given('I have answered 3 interview questions', target_fixture='reload_state')
def answered_3():
    client, storage, engine = _fresh_client()
    client.post('/tools/workflow_start', json={'arguments': {'project_meta': {}}})
    for qid in ['q-001', 'q-002', 'q-003']:
        client.post('/tools/workflow_record_answer', json={
            'arguments': {'question_id': qid, 'answer_text': 'answer'}
        })
    return {'db': _DB_RELOAD}


@given('the specification has been frozen', target_fixture='reload_state')
def spec_frozen_for_reload():
    client, storage, engine = _fresh_client()
    client.post('/tools/workflow_start', json={'arguments': {'project_meta': {}}})
    from orchestrator.workflow_server.catalog import QUESTIONS
    for qid, _ in QUESTIONS:
        client.post('/tools/workflow_record_answer', json={
            'arguments': {'question_id': qid, 'answer_text': 'a'}
        })
    client.post('/tools/workflow_freeze_spec', json={'arguments': {}})
    return {'db': _DB_RELOAD}


@given(parsers.parse('I have accepted tasks "{t1}" and "{t2}"'))
def pre_accept_two(reload_state):
    client = _reconnect_client(reload_state['db'])
    for tid in ['t-001', 't-002']:
        client.post('/tools/workflow_accept_task_result', json={'arguments': {
            'task_id': tid, 'summary': 'done',
            'artifacts_changed': [], 'tests_run': [], 'test_results': {}
        }})


@when('the workflow server is restarted', target_fixture='restarted_client')
def restart_server(reload_state):
    # Simulate restart: create a new app instance pointing at the same DB (no delete)
    return _reconnect_client(reload_state['db'])


@when('I request the next question', target_fixture='question_result')
def next_q_after_reload(restarted_client):
    r = restarted_client.post('/tools/workflow_next_question', json={'arguments': {}})
    return r.json()


@when('I request the next task', target_fixture='task_result')
def next_t_after_reload(restarted_client):
    r = restarted_client.post('/tools/workflow_next_task', json={'arguments': {}})
    return r.json()


@then(parsers.parse('the question id should be "{qid}"'))
def q_id_after_reload(question_result, qid):
    assert question_result.get('id') == qid


@then(parsers.parse('the task id should be "{tid}"'))
def t_id_after_reload(task_result, tid):
    assert task_result.get('id') == tid


@then(parsers.parse('the workflow phase should be "{phase}"'))
def phase_after_reload(restarted_client, phase):
    r = restarted_client.post('/tools/workflow_get_state', json={'arguments': {}})
    assert r.json()['phase'] == phase
