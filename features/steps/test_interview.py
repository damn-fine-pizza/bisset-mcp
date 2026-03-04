import pytest
from pytest_bdd import scenarios, given, when, then, parsers
from .conftest import _answer_all

scenarios('../interview_loop.feature')


@given('I have started a new workflow', target_fixture='workflow_client')
def started(started_client):
    return started_client


@when('I request the next question', target_fixture='question_result')
def next_question(workflow_client):
    r = workflow_client.post('/tools/workflow_next_question', json={'arguments': {}})
    assert r.status_code == 200
    return r.json()


@then(parsers.parse('the question id should be "{qid}"'))
def question_id_is(question_result, qid):
    assert question_result.get('id') == qid


@then(parsers.parse('the question text should contain "{text}"'))
def question_text_contains(question_result, text):
    assert text.lower() in question_result.get('text', '').lower()


@when(parsers.parse('I answer question "{qid}" with "{answer}"'))
def answer_question(workflow_client, qid, answer):
    r = workflow_client.post('/tools/workflow_record_answer', json={
        'arguments': {'question_id': qid, 'answer_text': answer}
    })
    assert r.status_code == 200


@when('I answer all 8 interview questions')
def answer_all_8(workflow_client):
    _answer_all(workflow_client)


@then('the response should indicate all questions are done')
def questions_done(question_result):
    assert question_result.get('done') is True


@given(parsers.parse('I have answered question "{qid}" with "{answer}"'))
def pre_answer(workflow_client, qid, answer):
    workflow_client.post('/tools/workflow_record_answer', json={
        'arguments': {'question_id': qid, 'answer_text': answer}
    })


@then(parsers.parse('the stored answer for "{qid}" should be "{expected}"'))
def stored_answer_is(workflow_client, qid, expected):
    r = workflow_client.post('/tools/workflow_get_state', json={'arguments': {}})
    # verify via next_question: the question should not appear as unanswered
    # instead query all answers via storage directly through the engine
    import orchestrator.workflow_server.app as app_module
    answers = dict((row[0], row[2]) for row in app_module._storage.get_all_answers())
    assert answers.get(qid) == expected
