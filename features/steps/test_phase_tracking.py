import pytest
from pytest_bdd import scenarios, given, when, then, parsers
from .conftest import _make_app
from fastapi.testclient import TestClient

scenarios('../phase_tracking.feature')

# ── helpers ──────────────────────────────────────────────────────────────────

_PHASE_SIGNALS = [
    'requirements_valid',
    'tasks_ready',
    'features_written',
    'implementation_complete',
    'coverage_passed',
]


def _advance(client, signal):
    return client.post('/tools/workflow_advance_phase',
                       json={'arguments': {'signal': signal}})


def _get_sub_phase(client):
    r = client.post('/tools/workflow_get_state', json={'arguments': {}})
    return r.json().get('sub_phase')


# ── shared fixtures ───────────────────────────────────────────────────────────

@given('the specification has been frozen', target_fixture='workflow_client')
def spec_frozen(frozen_client):
    return frozen_client


@given('sub_phase is phase_6_coverage', target_fixture='workflow_client')
def sub_phase_is_coverage(frozen_client):
    """Advance through phases until phase_6_coverage."""
    for sig in ['requirements_valid', 'tasks_ready', 'features_written', 'implementation_complete']:
        _advance(frozen_client, sig)
    return frozen_client


# ── when ──────────────────────────────────────────────────────────────────────

@when(parsers.parse('I advance the phase with signal "{signal}"'), target_fixture='advance_result')
def advance_phase(workflow_client, signal):
    r = _advance(workflow_client, signal)
    assert r.status_code == 200
    return r.json()


@when('I advance through all phases to done', target_fixture='advance_result')
def advance_all(workflow_client):
    for sig in _PHASE_SIGNALS:
        r = _advance(workflow_client, sig)
    return r.json()


# ── then ──────────────────────────────────────────────────────────────────────

@then(parsers.parse('the state should show sub_phase "{expected}"'))
def state_sub_phase(workflow_client, expected):
    actual = _get_sub_phase(workflow_client)
    assert actual == expected, f'Expected sub_phase={expected!r}, got {actual!r}'


@then(parsers.parse('the advance response should contain sub_phase "{expected}"'))
def advance_response_sub_phase(advance_result, expected):
    assert advance_result.get('sub_phase') == expected, (
        f'Expected advance response sub_phase={expected!r}, got {advance_result!r}')


@then('an error should be returned')
def advance_error(advance_result):
    assert 'error' in advance_result, f'Expected error, got: {advance_result}'


@then(parsers.parse('the phase should be "{expected}"'))
def phase_is(workflow_client, expected):
    r = workflow_client.post('/tools/workflow_get_state', json={'arguments': {}})
    actual = r.json().get('phase')
    assert actual == expected, f'Expected phase={expected!r}, got {actual!r}'
