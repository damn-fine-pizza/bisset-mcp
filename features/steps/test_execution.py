import pytest
from pytest_bdd import scenarios, given, when, then, parsers
from orchestrator.workflow_server.catalog import PLAN_TASKS

scenarios('../execution_loop.feature')


@given('the specification has been frozen', target_fixture='workflow_client')
def spec_frozen(frozen_client):
    return frozen_client


@given('all tasks have been completed', target_fixture='workflow_client')
def all_done(frozen_client):
    for tid, _ in PLAN_TASKS:
        frozen_client.post('/tools/workflow_accept_task_result', json={'arguments': {
            'task_id': tid, 'summary': 'done', 'artifacts_changed': [], 'tests_run': [], 'test_results': {}
        }})
    return frozen_client


@when('I request the next task', target_fixture='task_result')
def next_task(workflow_client):
    r = workflow_client.post('/tools/workflow_next_task', json={'arguments': {}})
    assert r.status_code == 200
    return r.json()


@then(parsers.parse('the task id should be "{tid}"'))
def task_id_is(task_result, tid):
    assert task_result.get('id') == tid


@then(parsers.parse('the task title should be "{title}"'))
def task_title_is(task_result, title):
    assert task_result.get('title') == title


@given(parsers.parse('I have accepted task "{tid}" with summary "{summary}"'))
def pre_accept(workflow_client, tid, summary):
    workflow_client.post('/tools/workflow_accept_task_result', json={'arguments': {
        'task_id': tid, 'summary': summary,
        'artifacts_changed': [], 'tests_run': [], 'test_results': {}
    }})


@when(parsers.parse('I accept task "{tid}" with summary "{summary}" and artifact "{artifact}"'), target_fixture='accept_result')
def accept_with_artifact(workflow_client, tid, summary, artifact):
    r = workflow_client.post('/tools/workflow_accept_task_result', json={'arguments': {
        'task_id': tid, 'summary': summary,
        'artifacts_changed': [artifact], 'tests_run': [], 'test_results': {}
    }})
    assert r.status_code == 200
    return r.json()


@then(parsers.parse('the evidence for task "{tid}" should be stored'))
def evidence_stored(workflow_client, tid, accept_result):
    import orchestrator.workflow_server.app as app_module
    import json
    tasks = {t[0]: t for t in app_module._storage.list_tasks()}
    assert tid in tasks
    evidence = json.loads(tasks[tid][5])
    assert evidence.get('summary') is not None


@when('I accept all default tasks')
def accept_all(workflow_client):
    for tid, _ in PLAN_TASKS:
        workflow_client.post('/tools/workflow_accept_task_result', json={'arguments': {
            'task_id': tid, 'summary': 'done',
            'artifacts_changed': [], 'tests_run': [], 'test_results': {}
        }})


@then('the workflow should be done')
def workflow_done(workflow_client):
    r = workflow_client.post('/tools/workflow_is_done', json={'arguments': {}})
    assert r.json()['done'] is True


@then('the response should indicate all tasks are done')
def tasks_done_signal(task_result):
    assert task_result.get('done') is True
