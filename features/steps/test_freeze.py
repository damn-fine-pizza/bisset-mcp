import os
import pytest
from pytest_bdd import scenarios, given, when, then, parsers
from .conftest import _answer_all

scenarios('../freeze_spec.feature')


@given('I have answered all interview questions', target_fixture='workflow_client')
def all_answered(answered_client):
    return answered_client


@given('I have answered all interview questions without project_path', target_fixture='workflow_client')
def all_answered_no_path(workflow_client):
    """Session started without project_path — freeze should be blocked."""
    workflow_client.post('/tools/workflow_new_session', json={'arguments': {'name': 'NoPP'}})
    workflow_client.post('/tools/workflow_start', json={'arguments': {'project_meta': {'name': 'NoPP'}}})
    _answer_all(workflow_client)
    return workflow_client


@given('I have already frozen the specification', target_fixture='workflow_client')
def already_frozen(frozen_client):
    return frozen_client


@when('I freeze the specification', target_fixture='freeze_result')
def do_freeze(workflow_client):
    r = workflow_client.post('/tools/workflow_freeze_spec', json={'arguments': {}})
    assert r.status_code == 200
    return r.json()


@when('I freeze the specification again', target_fixture='freeze_result')
def freeze_again(workflow_client):
    r = workflow_client.post('/tools/workflow_freeze_spec', json={'arguments': {}})
    assert r.status_code == 200
    return r.json()


@then(parsers.parse('the file "{filename}" should exist'))
def file_exists(freeze_result, filename):
    base = os.path.dirname(freeze_result['spec_path'])
    path = os.path.join(base, filename)
    assert os.path.exists(path), f'Expected file not found: {path}'


@then('it should contain my answers')
def spec_contains_answers(freeze_result):
    with open(freeze_result['spec_path']) as f:
        content = f.read()
    assert 'answer for q-001' in content


@then('it should have status "Proposed"')
def adr_has_proposed(freeze_result):
    base = os.path.dirname(freeze_result['spec_path'])
    adr_path = os.path.join(base, 'decisions', 'adr-0001.md')
    with open(adr_path) as f:
        content = f.read()
    assert 'Proposed' in content


@then(parsers.parse('it should contain the default tasks'))
def plan_has_default_tasks(freeze_result):
    from orchestrator.workflow_server.catalog import PLAN_TASKS
    base = os.path.dirname(freeze_result['spec_path'])
    plan_path = os.path.join(base, 'plan', 'workbreakdown.yaml')
    with open(plan_path) as f:
        content = f.read()
    assert content.count('id: t-') == len(PLAN_TASKS)


@then(parsers.parse('the workflow phase should be "{phase}"'))
def phase_is(workflow_client, phase):
    r = workflow_client.post('/tools/workflow_get_state', json={'arguments': {}})
    assert r.json()['phase'] == phase


@then(parsers.parse('the workflow phase should still be "{phase}"'))
def phase_still_is(workflow_client, phase):
    r = workflow_client.post('/tools/workflow_get_state', json={'arguments': {}})
    assert r.json()['phase'] == phase


@then('no error should be returned')
def no_error(freeze_result):
    assert 'error' not in freeze_result


@then(parsers.parse('an error field "{field}" with value "{value}" should be returned'))
def error_field_value(freeze_result, field, value):
    assert field in freeze_result, f'Expected field "{field}" in {freeze_result}'
    assert freeze_result[field] == value


@then(parsers.parse('the workflow phase should remain "{phase}"'))
def phase_remains(workflow_client, phase):
    r = workflow_client.post('/tools/workflow_get_state', json={'arguments': {}})
    assert r.json()['phase'] == phase
