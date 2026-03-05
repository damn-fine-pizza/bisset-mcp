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
    client.post('/tools/workflow_new_session', json={'arguments': {'name': 'ReloadTest'}})
    client.post('/tools/workflow_start', json={'arguments': {'project_meta': {'project_path': '/tmp/reload_test', 'test_runner': 'echo ok'}}})
    for qid in ['q-001', 'q-002', 'q-003']:
        client.post('/tools/workflow_record_answer', json={
            'arguments': {'question_id': qid, 'answer_text': 'answer'}
        })
    return {'db': _DB_RELOAD}


@given('the specification has been frozen', target_fixture='reload_state')
def spec_frozen_for_reload():
    client, storage, engine = _fresh_client()
    client.post('/tools/workflow_new_session', json={'arguments': {'name': 'ReloadTest'}})
    client.post('/tools/workflow_start', json={'arguments': {'project_meta': {'project_path': '/tmp/reload_test', 'test_runner': 'echo ok'}}})
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
    # restore active session
    sessions_r = client.post('/tools/workflow_list_sessions', json={'arguments': {}})
    sessions = sessions_r.json().get('sessions', [])
    if sessions:
        client.post('/tools/workflow_switch_session', json={'arguments': {'session_id': sessions[0]['id']}})
    for tid in ['t-001', 't-002']:
        client.post('/tools/workflow_accept_task_result', json={'arguments': {
            'task_id': tid, 'summary': 'done',
            'artifacts_changed': [], 'tests_run': [], 'test_results': {}
        }})


@when('the workflow server is restarted', target_fixture='restarted_client')
def restart_server(reload_state):
    # Simulate restart: create a new app instance pointing at the same DB (no delete)
    client = _reconnect_client(reload_state['db'])
    # restore active session (simulate client calling switch_session after restart)
    sessions_r = client.post('/tools/workflow_list_sessions', json={'arguments': {}})
    sessions = sessions_r.json().get('sessions', [])
    if sessions:
        client.post('/tools/workflow_switch_session', json={'arguments': {'session_id': sessions[0]['id']}})
    return client


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


@then('recording a new answer should not crash')
def answer_after_restart(restarted_client):
    r = restarted_client.post('/tools/workflow_record_answer', json={
        'arguments': {'question_id': 'q-004', 'answer_text': 'answer after restart'}
    })
    assert r.status_code == 200
    assert 'error' not in r.json()


@then(parsers.parse('the workflow phase should be "{phase}"'))
def phase_after_reload(restarted_client, phase):
    r = restarted_client.post('/tools/workflow_get_state', json={'arguments': {}})
    assert r.json()['phase'] == phase


# ── resume / list_sessions ────────────────────────────────────────────────────

@given(parsers.parse('the phase has been advanced to "{target}"'))
def advance_to_target(reload_state):
    client = _reconnect_client(reload_state['db'])
    sessions_r = client.post('/tools/workflow_list_sessions', json={'arguments': {}})
    sessions = sessions_r.json().get('sessions', [])
    if sessions:
        client.post('/tools/workflow_switch_session', json={'arguments': {'session_id': sessions[0]['id']}})
    client.post('/tools/workflow_advance_phase', json={'arguments': {'signal': 'requirements_valid'}})
    reload_state['client_after_advance'] = client


@when('I list all sessions', target_fixture='sessions_result')
def list_sessions(reload_state):
    client = reload_state.get('client_after_advance') or _reconnect_client(reload_state['db'])
    r = client.post('/tools/workflow_list_sessions', json={'arguments': {}})
    assert r.status_code == 200
    sessions = r.json().get('sessions', [])
    assert sessions, 'No sessions returned'
    return sessions[0]  # most recent


@then(parsers.parse('the session entry should include phase "{expected}"'))
def session_has_phase(sessions_result, expected):
    assert sessions_result.get('phase') == expected, (
        f"Expected phase={expected!r}, got {sessions_result}")


@then(parsers.parse('the session entry should include sub_phase "{expected}"'))
def session_has_sub_phase(sessions_result, expected):
    assert sessions_result.get('sub_phase') == expected, (
        f"Expected sub_phase={expected!r}, got {sessions_result}")


@then(parsers.parse('the session entry should include tasks_done {n:d}'))
def session_tasks_done(sessions_result, n):
    progress = sessions_result.get('progress', {})
    assert progress.get('tasks_done') == n, f"Expected tasks_done={n}, got {progress}"


@then('the session entry should include tasks_total greater than 0')
def session_tasks_total(sessions_result):
    progress = sessions_result.get('progress', {})
    assert progress.get('tasks_total', 0) > 0, f"Expected tasks_total>0, got {progress}"


@when('I switch to the current session', target_fixture='switch_result')
def switch_current(reload_state):
    client = _reconnect_client(reload_state['db'])
    sessions_r = client.post('/tools/workflow_list_sessions', json={'arguments': {}})
    sessions = sessions_r.json().get('sessions', [])
    assert sessions
    # advance so there's a non-null sub_phase to check
    client.post('/tools/workflow_switch_session', json={'arguments': {'session_id': sessions[0]['id']}})
    client.post('/tools/workflow_advance_phase', json={'arguments': {'signal': 'requirements_valid'}})
    r = client.post('/tools/workflow_switch_session', json={'arguments': {'session_id': sessions[0]['id']}})
    return r.json()


@then(parsers.parse('the switch response should include sub_phase "{expected}"'))
def switch_has_sub_phase(switch_result, expected):
    assert switch_result.get('sub_phase') == expected, (
        f"Expected sub_phase={expected!r}, got {switch_result}")
