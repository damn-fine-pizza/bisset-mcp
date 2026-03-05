import pytest
from pytest_bdd import scenarios, given, when, then, parsers
from .conftest import _accept_all

scenarios('../add_task.feature')


@given('the specification has been frozen', target_fixture='workflow_client')
def spec_frozen(frozen_client):
    return frozen_client


@given('all default tasks are accepted')
def accept_defaults(workflow_client):
    _accept_all(workflow_client)


@given('no session is active', target_fixture='workflow_client')
def no_session():
    """Return a fresh TestClient with NO session started."""
    import os
    db = '/tmp/bdd_add_task_nosession.db'
    try:
        os.remove(db)
    except FileNotFoundError:
        pass
    import orchestrator.workflow_server.app as app_module
    from orchestrator.workflow_server.storage import Storage
    from orchestrator.workflow_server.catalog import Catalog
    from orchestrator.workflow_server.renderers import Renderers
    from orchestrator.workflow_server.engine import WorkflowEngine
    from fastapi.testclient import TestClient
    storage = Storage(db)
    catalog = Catalog()
    renderers = Renderers(storage)
    engine = WorkflowEngine(storage, catalog, renderers)
    app_module._storage = storage
    app_module._catalog = catalog
    app_module._renderers = renderers
    app_module._engine = engine
    with TestClient(app_module.app) as client:
        yield client
    try:
        os.remove(db)
    except FileNotFoundError:
        pass


@when(parsers.parse('I add a task with id "{tid}" and title "{title}"'), target_fixture='add_result')
def add_task_basic(workflow_client, tid, title):
    r = workflow_client.post('/tools/workflow_add_task', json={'arguments': {
        'task_id': tid, 'title': title
    }})
    assert r.status_code == 200
    return r.json()


@when(parsers.parse('I add a task with id "{tid}" and title "{title}" and acceptance criteria "{ac}"'), target_fixture='add_result')
def add_task_with_ac(workflow_client, tid, title, ac):
    r = workflow_client.post('/tools/workflow_add_task', json={'arguments': {
        'task_id': tid, 'title': title, 'acceptance_criteria': ac.replace('\\n', '\n')
    }})
    assert r.status_code == 200
    return r.json()


@then(parsers.parse('the task list should contain "{tid}"'))
def task_list_contains(workflow_client, tid):
    r = workflow_client.post('/tools/workflow_list_tasks', json={'arguments': {}})
    ids = [t['id'] for t in r.json()['tasks']]
    assert tid in ids, f'{tid!r} not found in {ids}'


@then(parsers.parse('the task "{tid}" should have acceptance_criteria set'))
def task_has_ac(workflow_client, tid):
    r = workflow_client.post('/tools/workflow_list_tasks', json={'arguments': {}})
    tasks = {t['id']: t for t in r.json()['tasks']}
    assert tid in tasks
    assert tasks[tid].get('acceptance_criteria'), f'acceptance_criteria empty for {tid}'


@when(parsers.parse('I add a task with id "{tid}" and title "{title}" and negative criteria "{nac}"'), target_fixture='add_result')
def add_task_with_nac(workflow_client, tid, title, nac):
    r = workflow_client.post('/tools/workflow_add_task', json={'arguments': {
        'task_id': tid, 'title': title, 'negative_acceptance_criteria': nac.replace('\\n', '\n')
    }})
    assert r.status_code == 200
    return r.json()


@then(parsers.parse('the task "{tid}" should have negative_acceptance_criteria set'))
def task_has_nac(workflow_client, tid):
    r = workflow_client.post('/tools/workflow_list_tasks', json={'arguments': {}})
    tasks = {t['id']: t for t in r.json()['tasks']}
    assert tid in tasks
    assert tasks[tid].get('negative_acceptance_criteria'), (
        f'negative_acceptance_criteria empty for {tid}')


@when('I request the next task', target_fixture='task_result')
def next_task(workflow_client):
    r = workflow_client.post('/tools/workflow_next_task', json={'arguments': {}})
    assert r.status_code == 200
    return r.json()


@then(parsers.parse('the task id should be "{tid}"'))
def task_id_is(task_result, tid):
    assert task_result.get('id') == tid


@then('an error should be returned')
def error_returned(add_result):
    assert 'error' in add_result
