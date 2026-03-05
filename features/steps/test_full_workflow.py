import os
import pytest
from pytest_bdd import scenarios, given, when, then, parsers
from fastapi.testclient import TestClient
from orchestrator.workflow_server.catalog import QUESTIONS

scenarios('../full_workflow.feature')

DB = '/tmp/bdd_full_workflow.db'

# ── helpers ───────────────────────────────────────────────────────────────────

def _build_client(db_path):
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
    return TestClient(app_module.app), storage, engine


def _advance(client, signal):
    r = client.post('/tools/workflow_advance_phase', json={'arguments': {'signal': signal}})
    assert r.status_code == 200
    return r.json()


def _sub_phase(client):
    r = client.post('/tools/workflow_get_state', json={'arguments': {}})
    return r.json().get('sub_phase')


def _phase(client):
    r = client.post('/tools/workflow_get_state', json={'arguments': {}})
    return r.json().get('phase')


# ── given ─────────────────────────────────────────────────────────────────────

@given('a fresh session is created', target_fixture='workflow_state')
def fresh_session():
    try:
        os.remove(DB)
    except FileNotFoundError:
        pass
    client, storage, engine = _build_client(DB)
    client.post('/tools/workflow_new_session', json={'arguments': {'name': 'E2ETest'}})
    client.post('/tools/workflow_start', json={'arguments': {'project_meta': {'name': 'E2ETest', 'project_path': '/tmp/e2e_test_project', 'test_runner': 'echo ok'}}})
    yield {'client': client, 'db': DB}
    try:
        os.remove(DB)
    except FileNotFoundError:
        pass


@given('all interview questions are answered')
def answer_all(workflow_state):
    client = workflow_state['client']
    for qid, _ in QUESTIONS:
        client.post('/tools/workflow_record_answer', json={
            'arguments': {'question_id': qid, 'answer_text': f'answer for {qid}'}
        })


@given('the spec is frozen')
def freeze(workflow_state):
    workflow_state['client'].post('/tools/workflow_freeze_spec', json={'arguments': {}})


@given(parsers.parse('sub_phase is advanced to "{target}"'))
def advance_to(workflow_state, target):
    client = workflow_state['client']
    chain = {
        'phase_3_architect':  ['requirements_valid'],
        'phase_4_gherkin':    ['requirements_valid', 'tasks_ready'],
        'phase_5_implement':  ['requirements_valid', 'tasks_ready', 'features_written'],
        'phase_6_coverage':   ['requirements_valid', 'tasks_ready', 'features_written', 'implementation_complete'],
    }
    for sig in chain[target]:
        _advance(client, sig)


@given('the engine is reinitialised from the same database')
def reinit_engine(workflow_state):
    db = workflow_state['db']
    # read the active session id from the existing storage first
    import orchestrator.workflow_server.app as app_module
    sid = app_module._storage._active_session_id
    new_client, new_storage, _ = _build_client(db)
    new_storage.set_active_session(sid)
    new_client.post('/tools/workflow_switch_session', json={'arguments': {'session_id': sid}})
    workflow_state['client'] = new_client


# ── when ──────────────────────────────────────────────────────────────────────

@when(parsers.parse('I call advance_phase "{signal}"'))
def call_advance(workflow_state, signal):
    r = _advance(workflow_state['client'], signal)
    assert 'error' not in r, f'advance_phase failed: {r}'


@when('the engine is reinitialised from the same database')
def reinit_engine_when(workflow_state):
    reinit_engine(workflow_state)


# ── then ──────────────────────────────────────────────────────────────────────

@then(parsers.parse('the state should show sub_phase "{expected}"'))
def check_sub_phase(workflow_state, expected):
    actual = _sub_phase(workflow_state['client'])
    assert actual == expected, f'sub_phase: expected {expected!r}, got {actual!r}'


@then(parsers.parse('the phase should be "{expected}"'))
def check_phase(workflow_state, expected):
    actual = _phase(workflow_state['client'])
    assert actual == expected, f'phase: expected {expected!r}, got {actual!r}'


@then('the workflow should be done')
def workflow_done(workflow_state):
    r = workflow_state['client'].post('/tools/workflow_is_done', json={'arguments': {}})
    assert r.json()['done'] is True
