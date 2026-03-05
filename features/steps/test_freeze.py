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
    return {'resp': r.json(), 'client': workflow_client}


@when('I freeze the specification again', target_fixture='freeze_result')
def freeze_again(workflow_client):
    r = workflow_client.post('/tools/workflow_freeze_spec', json={'arguments': {}})
    assert r.status_code == 200
    return {'resp': r.json(), 'client': workflow_client}


@then(parsers.parse('the file "{filename}" should exist'))
def file_exists(freeze_result, filename):
    # Resources are now stored in DB; use the resources endpoint to retrieve content
    # Map expected filenames to resource names
    mapping = {
        'spec_current.md': 'spec_current',
        'plan/workbreakdown.yaml': 'plan_workbreakdown',
    }
    if filename.startswith('decisions/'):
        # decisions/adr-0001.md -> adr:adr-0001
        adr_id = os.path.basename(filename).replace('.md', '')
        r = freeze_result['client'].get(f"/resources/adr:{adr_id}")
    else:
        res_name = mapping.get(filename)
        r = freeze_result['client'].get(f"/resources/{res_name}")
    assert r.status_code == 200, f'Expected resource not found for {filename}: {r.status_code} {r.text}'


@then('it should contain my answers')
def spec_contains_answers(freeze_result):
    r = freeze_result['client'].get('/resources/spec_current')
    assert r.status_code == 200
    content = r.json().get('content', '')
    assert 'answer for q-001' in content


@then('it should have status "Proposed"')
def adr_has_proposed(freeze_result):
    r = freeze_result['client'].get('/resources/adr:adr-0001')
    assert r.status_code == 200
    content = r.json().get('content', '')
    assert 'Proposed' in content


@then(parsers.parse('it should contain the default tasks'))
def plan_has_default_tasks(freeze_result):
    from orchestrator.workflow_server.catalog import PLAN_TASKS
    r = freeze_result['client'].get('/resources/plan_workbreakdown')
    assert r.status_code == 200
    content = r.json().get('content', '') or ''
    # content may be structured JSON when stored in DB; normalize to string
    if isinstance(content, dict):
        s = '\n'.join([t['id'] for t in content.get('tasks', [])])
    else:
        s = str(content)
    assert s.count('t-') == len(PLAN_TASKS)


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
    resp = freeze_result.get('resp') if isinstance(freeze_result, dict) else freeze_result
    assert field in resp, f'Expected field "{field}" in {resp}'
    assert resp[field] == value


@then(parsers.parse('the workflow phase should remain "{phase}"'))
def phase_remains(workflow_client, phase):
    r = workflow_client.post('/tools/workflow_get_state', json={'arguments': {}})
    assert r.json()['phase'] == phase
