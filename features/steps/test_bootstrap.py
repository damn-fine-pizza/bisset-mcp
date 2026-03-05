import pytest
from pytest_bdd import scenarios, given, when, then, parsers
from .conftest import _answer_all

scenarios('../project_bootstrap.feature')


@given('the workflow server is running', target_fixture='workflow_client')
def wf_running(workflow_client):
    return workflow_client


@given(parsers.parse('I start a new workflow for project "{name}"'))
def start_workflow_given(workflow_client, name):
    workflow_client.post('/tools/workflow_new_session', json={'arguments': {'name': name}})
    r = workflow_client.post('/tools/workflow_start', json={'arguments': {'project_meta': {'name': name, 'project_path': '/tmp/test_project', 'test_runner': 'echo ok'}}})
    assert r.status_code == 200


@when(parsers.parse('I start a new workflow for project "{name}"'))
def start_workflow_when(workflow_client, name):
    workflow_client.post('/tools/workflow_new_session', json={'arguments': {'name': name}})
    r = workflow_client.post('/tools/workflow_start', json={'arguments': {'project_meta': {'name': name, 'project_path': '/tmp/test_project', 'test_runner': 'echo ok'}}})
    assert r.status_code == 200


@when('I answer all the interview questions')
def answer_all(workflow_client):
    _answer_all(workflow_client)


@when('I freeze the specification', target_fixture='freeze_result')
def freeze(workflow_client):
    r = workflow_client.post('/tools/workflow_freeze_spec', json={'arguments': {}})
    assert r.status_code == 200
    return {'resp': r.json(), 'client': workflow_client}


@then('a specification document should exist')
def spec_exists(freeze_result):
    r = freeze_result['client'].get('/resources/spec_current')
    assert r.status_code == 200


@then('an ADR stub should exist')
def adr_exists(freeze_result):
    r = freeze_result['client'].get('/resources/adr:adr-0001')
    assert r.status_code == 200


@then('a work breakdown should exist')
def plan_exists(freeze_result):
    r = freeze_result['client'].get('/resources/plan_workbreakdown')
    assert r.status_code == 200


@then(parsers.parse('the workflow should be in "{phase}" phase'))
def workflow_in_phase(workflow_client, phase):
    r = workflow_client.post('/tools/workflow_get_state', json={'arguments': {}})
    assert r.json()['phase'] == phase


@then(parsers.parse('the workflow state should show phase "{phase}"'))
def state_shows_phase(workflow_client, phase):
    r = workflow_client.post('/tools/workflow_get_state', json={'arguments': {}})
    assert r.json()['phase'] == phase
