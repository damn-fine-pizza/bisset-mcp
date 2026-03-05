import os
import tempfile
import pytest
from pytest_bdd import scenarios, given, when, then, parsers
from .conftest import _answer_all

scenarios('../autonomous_loop.feature')


# ── shared helpers ────────────────────────────────────────────────────────────

def _freeze(client):
    _answer_all(client)
    client.post('/tools/workflow_freeze_spec', json={'arguments': {}})


# ── workflow_status ──────────────────────────────────────────────────────────

@given('I have a session in execution phase with some tasks', target_fixture='status_client')
def session_with_tasks(workflow_client):
    workflow_client.post('/tools/workflow_new_session', json={'arguments': {'name': 'StatusTest'}})
    workflow_client.post('/tools/workflow_start', json={'arguments': {'project_meta': {
        'project_path': '/tmp/status_test', 'test_runner': 'echo ok'
    }}})
    _freeze(workflow_client)
    return workflow_client


@when('I call workflow_status', target_fixture='status_result')
def call_status(status_client):
    r = status_client.post('/tools/workflow_status', json={'arguments': {}})
    assert r.status_code == 200
    return r.json()


@then(parsers.parse('the response includes "{field}" equal to "{value}"'))
def response_field_equals_str(request, field, value):
    result = _get_result(request)
    actual = result.get(field)
    assert str(actual) == value, f'Expected {field}={value!r} but got {actual!r}'


def _get_result(request):
    """Pick whichever result fixture is available in the current test."""
    for name in ('status_result', 'loop_result', 'bootstrap_result', 'events_result'):
        try:
            return request.getfixturevalue(name)
        except pytest.FixtureLookupError:
            pass
    raise RuntimeError('No result fixture found')


@then(parsers.parse('the response includes a "{field}" field'))
def response_has_field(request, field):
    result = _get_result(request)
    assert field in result, f'Expected field {field!r} in {result}'


@then(parsers.parse('the response includes "{field}" with an id field'))
def response_field_has_id(request, field):
    result = _get_result(request)
    obj = result.get(field)
    assert obj is not None, f'Expected {field!r} to be present'
    assert 'id' in obj, f'Expected {field}["id"] to exist, got {obj!r}'


# ── workflow_bootstrap_project ───────────────────────────────────────────────

@given('a Python BDD project directory', target_fixture='py_dir')
def py_dir_fixture():
    d = tempfile.mkdtemp()
    open(os.path.join(d, 'pyproject.toml'), 'w').close()
    os.makedirs(os.path.join(d, 'features'))
    return d


@given('a Rust project directory', target_fixture='rust_dir')
def rust_dir_fixture():
    d = tempfile.mkdtemp()
    open(os.path.join(d, 'Cargo.toml'), 'w').close()
    return d


@when('I bootstrap that directory', target_fixture='bootstrap_result')
def call_bootstrap(workflow_client, request):
    # pick whichever dir fixture is active
    d = None
    for fname in ('py_dir', 'rust_dir'):
        try:
            d = request.getfixturevalue(fname)
            break
        except pytest.FixtureLookupError:
            pass
    r = workflow_client.post('/tools/workflow_bootstrap_project', json={'arguments': {'cwd': d}})
    assert r.status_code == 200
    return r.json()


@when('I bootstrap that directory into the session', target_fixture='bootstrap_result')
def call_bootstrap_merge(workflow_client, py_dir):
    r = workflow_client.post('/tools/workflow_bootstrap_project', json={'arguments': {'cwd': py_dir}})
    assert r.status_code == 200
    return r.json()


@when('I bootstrap a non-existent directory', target_fixture='bootstrap_result')
def call_bootstrap_bad(workflow_client):
    r = workflow_client.post('/tools/workflow_bootstrap_project', json={'arguments': {'cwd': '/nonexistent/path/abc'}})
    assert r.status_code == 200
    return r.json()


@then(parsers.parse('the detected test_runner is "{runner}"'))
def detected_runner(bootstrap_result, runner):
    assert bootstrap_result.get('detected', {}).get('test_runner') == runner, bootstrap_result


@then(parsers.parse('the detected features_dir is "{fdir}"'))
def detected_features_dir(bootstrap_result, fdir):
    assert bootstrap_result.get('detected', {}).get('features_dir') == fdir, bootstrap_result


@then('the detected project_path matches the directory')
def detected_path(bootstrap_result, request):
    d = None
    for fname in ('py_dir', 'rust_dir'):
        try:
            d = request.getfixturevalue(fname)
            break
        except pytest.FixtureLookupError:
            pass
    assert bootstrap_result.get('detected', {}).get('project_path') == d, bootstrap_result


@given('I have an active session with project_path not set', target_fixture='workflow_client')
def session_no_path(workflow_client):
    workflow_client.post('/tools/workflow_new_session', json={'arguments': {'name': 'BootTest'}})
    workflow_client.post('/tools/workflow_start', json={'arguments': {'project_meta': {'name': 'BootTest'}}})
    return workflow_client


@then('the response merged_into_session is true')
def merged(bootstrap_result):
    assert bootstrap_result.get('merged_into_session') is True, bootstrap_result


@then('the session project_meta now contains a project_path')
def meta_has_path(workflow_client):
    r = workflow_client.post('/tools/workflow_get_state', json={'arguments': {}})
    pm = r.json().get('project_meta') or {}
    assert pm.get('project_path'), f'project_path not in project_meta: {pm}'


@then('the response includes an "error" field')
def has_error(request):
    result = _get_result(request)
    assert 'error' in result, result


# ── workflow_run_until_blocked ────────────────────────────────────────────────

@given('I have a session in execution phase', target_fixture='exec_client')
def session_in_exec(workflow_client):
    workflow_client.post('/tools/workflow_new_session', json={'arguments': {'name': 'LoopTest'}})
    workflow_client.post('/tools/workflow_start', json={'arguments': {'project_meta': {
        'project_path': '/tmp/loop_test', 'test_runner': 'echo ok'
    }}})
    _freeze(workflow_client)
    return workflow_client


@given('I have a session where all tasks are pre-accepted', target_fixture='exec_client')
def session_pre_done(workflow_client):
    workflow_client.post('/tools/workflow_new_session', json={'arguments': {'name': 'PreDoneTest'}})
    workflow_client.post('/tools/workflow_start', json={'arguments': {'project_meta': {
        'project_path': '/tmp/predone_test', 'test_runner': 'echo ok'
    }}})
    _freeze(workflow_client)
    r = workflow_client.post('/tools/workflow_list_tasks', json={'arguments': {}})
    tasks = r.json().get('tasks', [])
    for t in tasks:
        workflow_client.post('/tools/workflow_accept_task_result', json={'arguments': {
            'task_id': t['id'], 'summary': 'pre-done',
            'artifacts_changed': [], 'tests_run': [], 'test_results': {},
        }})
    return workflow_client


@when(parsers.parse('I call workflow_run_until_blocked with max_iterations {n:d}'), target_fixture='loop_result')
def call_loop(exec_client, n):
    r = exec_client.post('/tools/workflow_run_until_blocked', json={'arguments': {'max_iterations': n}})
    assert r.status_code == 200
    return r.json()


@then(parsers.parse('the response status is "{status}"'))
def loop_status(request, status):
    result = _get_result(request)
    assert result.get('status') == status, result


@then(parsers.parse('the response includes a "{field}" field'))
def has_field(request, field):
    result = _get_result(request)
    assert field in result, f'Expected field {field!r} in {result}'


# ── workflow_get_events ──────────────────────────────────────────────────────

@given('I have a session with some tool calls recorded', target_fixture='events_client')
def session_with_events(workflow_client):
    workflow_client.post('/tools/workflow_new_session', json={'arguments': {'name': 'EventsTest'}})
    workflow_client.post('/tools/workflow_start', json={'arguments': {'project_meta': {
        'name': 'EventsTest', 'project_path': '/tmp/events_test', 'test_runner': 'echo'
    }}})
    workflow_client.post('/tools/workflow_get_state', json={'arguments': {}})
    return workflow_client


@when(parsers.parse('I call workflow_get_events with limit {n:d}'), target_fixture='events_result')
def call_get_events(events_client, n):
    r = events_client.post('/tools/workflow_get_events', json={'arguments': {'limit': n}})
    assert r.status_code == 200
    return r.json()


@then('the response includes an "events" list')
def events_list(events_result):
    assert 'events' in events_result, events_result
    assert isinstance(events_result['events'], list)


@then('each event has "tool" and "timestamp" fields')
def events_have_fields(events_result):
    for ev in events_result['events']:
        assert 'tool' in ev, ev
        assert 'timestamp' in ev, ev
