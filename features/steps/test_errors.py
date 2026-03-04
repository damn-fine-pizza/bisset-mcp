import pytest
from pytest_bdd import scenarios, given, when, then, parsers

scenarios('../error_handling.feature')


@given('I have started a new workflow', target_fixture='workflow_client')
def started(started_client):
    return started_client


@given('I have started a new workflow with no answers', target_fixture='workflow_client')
def started_no_answers(started_client):
    return started_client


@when('I request the next task', target_fixture='task_result')
def next_task(workflow_client):
    r = workflow_client.post('/tools/workflow_next_task', json={'arguments': {}})
    assert r.status_code == 200
    return r.json()


@then('the response should contain an error')
def has_error(task_result):
    assert 'error' in task_result


@then(parsers.parse('the error should mention "{text}"'))
def error_mentions(task_result, text):
    assert text in task_result.get('error', '')


@when(parsers.parse('I answer question "{qid}" with "{answer}"'), target_fixture='answer_result')
def answer_question(workflow_client, qid, answer):
    r = workflow_client.post('/tools/workflow_record_answer', json={
        'arguments': {'question_id': qid, 'answer_text': answer}
    })
    return r


@then('no error should be raised')
def no_error_raised(answer_result):
    assert answer_result.status_code == 200


@when('I freeze the specification', target_fixture='freeze_result')
def freeze(workflow_client):
    r = workflow_client.post('/tools/workflow_freeze_spec', json={'arguments': {}})
    assert r.status_code == 200
    return r.json()


@then(parsers.parse('the specification should contain "UNANSWERED" for all fields'))
def spec_has_unanswered(freeze_result):
    with open(freeze_result['spec_path']) as f:
        content = f.read()
    assert '_UNANSWERED_' in content
