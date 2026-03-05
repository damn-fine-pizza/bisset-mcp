import os
import pytest
from pytest_bdd import scenarios, given, when, then, parsers
from .conftest import _make_app
from fastapi.testclient import TestClient

scenarios('../architecture_proposals.feature')

# ── shared fixtures ───────────────────────────────────────────────────────────

@given('the specification has been frozen', target_fixture='workflow_client')
def spec_frozen(frozen_client):
    return frozen_client


@given('no session is active', target_fixture='workflow_client')
def no_session():
    db = '/tmp/bdd_proposals_nosession.db'
    try:
        os.remove(db)
    except FileNotFoundError:
        pass
    import orchestrator.workflow_server.app as app_module
    from orchestrator.workflow_server.storage import Storage
    from orchestrator.workflow_server.catalog import Catalog
    from orchestrator.workflow_server.renderers import Renderers
    from orchestrator.workflow_server.engine import WorkflowEngine
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


# ── when ──────────────────────────────────────────────────────────────────────

@when(parsers.parse('I store a proposal with paradigm "{paradigm}" and content "{content}"'),
      target_fixture='store_result')
def store_proposal(workflow_client, paradigm, content):
    r = workflow_client.post('/tools/workflow_store_proposal', json={'arguments': {
        'paradigm': paradigm, 'content': content
    }})
    assert r.status_code == 200
    return r.json()


@when("I store proposals for \"oop\", \"functional\", \"data-oriented\"")
def store_three_proposals(workflow_client):
    for paradigm in ['oop', 'functional', 'data-oriented']:
        workflow_client.post('/tools/workflow_store_proposal', json={'arguments': {
            'paradigm': paradigm, 'content': f'{paradigm} content'
        }})


@when('I list proposals', target_fixture='proposals_result')
def list_proposals(workflow_client):
    r = workflow_client.post('/tools/workflow_list_proposals', json={'arguments': {}})
    assert r.status_code == 200
    return r.json()


# ── then ──────────────────────────────────────────────────────────────────────

@then(parsers.parse('the proposals list should contain {n:d} entries'))
def proposals_count(proposals_result, n):
    proposals = proposals_result.get('proposals', [])
    assert len(proposals) == n, f'Expected {n} proposals, got {len(proposals)}: {proposals}'


@then(parsers.parse('the proposal paradigm should be "{paradigm}"'))
def proposal_paradigm(proposals_result, paradigm):
    paradigms = [p['paradigm'] for p in proposals_result.get('proposals', [])]
    assert paradigm in paradigms, f'{paradigm!r} not in {paradigms}'


@then(parsers.parse('the proposal content for "{paradigm}" should contain "{text}"'))
def proposal_content_contains(proposals_result, paradigm, text):
    proposals = {p['paradigm']: p for p in proposals_result.get('proposals', [])}
    assert paradigm in proposals, f'{paradigm!r} not found'
    assert text in proposals[paradigm].get('content', ''), (
        f'{text!r} not in content for {paradigm!r}')


@then('an error should be returned')
def proposal_error(store_result):
    assert 'error' in store_result, f'Expected error, got: {store_result}'
