"""
Tests for workflow_server using FastAPI TestClient.
Covers all tool endpoints, resource endpoints, and engine state transitions.
"""
import os
import unittest
from fastapi.testclient import TestClient

DB = '/tmp/test_workflow_server.db'
os.environ['WORKFLOW_TEST_DB'] = DB  # picked up via monkeypatching below


class TestWorkflowServerTools(unittest.TestCase):

    def setUp(self):
        # Patch DB path before importing app to get a fresh DB each test
        try:
            os.remove(DB)
        except FileNotFoundError:
            pass
        import importlib
        import orchestrator.workflow_server.app as app_module
        # Reinitialise engine with test DB
        from orchestrator.workflow_server.storage import Storage
        from orchestrator.workflow_server.catalog import Catalog
        from orchestrator.workflow_server.renderers import Renderers
        from orchestrator.workflow_server.engine import WorkflowEngine
        storage = Storage(DB)
        catalog = Catalog()
        renderers = Renderers(storage)
        engine = WorkflowEngine(storage, catalog, renderers)
        app_module._storage = storage
        app_module._catalog = catalog
        app_module._renderers = renderers
        app_module._engine = engine
        self.client = TestClient(app_module.app)

    def tearDown(self):
        try:
            os.remove(DB)
        except FileNotFoundError:
            pass

    def test_health(self):
        r = self.client.get('/health')
        self.assertEqual(r.status_code, 200)
        self.assertTrue(r.json()['ok'])

    def test_start(self):
        r = self.client.post('/tools/workflow_start', json={'arguments': {'project_meta': {'name': 'test'}}})
        self.assertEqual(r.status_code, 200)
        self.assertEqual(r.json()['status'], 'started')

    def test_get_state(self):
        self.client.post('/tools/workflow_start', json={'arguments': {'project_meta': {}}})
        r = self.client.post('/tools/workflow_get_state', json={'arguments': {}})
        self.assertEqual(r.status_code, 200)
        self.assertEqual(r.json()['phase'], 'interview')

    def test_next_question(self):
        self.client.post('/tools/workflow_start', json={'arguments': {'project_meta': {}}})
        r = self.client.post('/tools/workflow_next_question', json={'arguments': {}})
        self.assertEqual(r.status_code, 200)
        self.assertIn('id', r.json())

    def test_record_answer(self):
        self.client.post('/tools/workflow_start', json={'arguments': {'project_meta': {}}})
        q = self.client.post('/tools/workflow_next_question', json={'arguments': {}}).json()
        r = self.client.post('/tools/workflow_record_answer', json={'arguments': {
            'question_id': q['id'], 'answer_text': 'test answer'
        }})
        self.assertEqual(r.status_code, 200)
        self.assertTrue(r.json()['ok'])

    def _full_interview(self):
        self.client.post('/tools/workflow_start', json={'arguments': {'project_meta': {'name': 'p'}}})
        while True:
            q = self.client.post('/tools/workflow_next_question', json={'arguments': {}}).json()
            if q.get('done'):
                break
            self.client.post('/tools/workflow_record_answer', json={'arguments': {
                'question_id': q['id'], 'answer_text': 'answer'
            }})

    def test_freeze_spec(self):
        self._full_interview()
        r = self.client.post('/tools/workflow_freeze_spec', json={'arguments': {}})
        self.assertEqual(r.status_code, 200)
        self.assertIn('spec_path', r.json())

    def test_next_task_after_freeze(self):
        self._full_interview()
        self.client.post('/tools/workflow_freeze_spec', json={'arguments': {}})
        r = self.client.post('/tools/workflow_next_task', json={'arguments': {}})
        self.assertEqual(r.status_code, 200)
        self.assertIn('id', r.json())

    def test_accept_task_result(self):
        self._full_interview()
        self.client.post('/tools/workflow_freeze_spec', json={'arguments': {}})
        t = self.client.post('/tools/workflow_next_task', json={'arguments': {}}).json()
        r = self.client.post('/tools/workflow_accept_task_result', json={'arguments': {
            'task_id': t['id'], 'summary': 'done', 'artifacts_changed': [], 'tests_run': [], 'test_results': {}
        }})
        self.assertEqual(r.status_code, 200)
        self.assertTrue(r.json()['ok'])

    def test_report(self):
        self.client.post('/tools/workflow_start', json={'arguments': {'project_meta': {}}})
        r = self.client.post('/tools/workflow_report', json={'arguments': {}})
        self.assertEqual(r.status_code, 200)
        self.assertIn('phase', r.json())

    def test_is_done_false_initially(self):
        self.client.post('/tools/workflow_start', json={'arguments': {'project_meta': {}}})
        r = self.client.post('/tools/workflow_is_done', json={'arguments': {}})
        self.assertFalse(r.json()['done'])

    def test_complete_workflow_is_done(self):
        from orchestrator.workflow_server.catalog import PLAN_TASKS
        self._full_interview()
        self.client.post('/tools/workflow_freeze_spec', json={'arguments': {}})
        for tid, _ in PLAN_TASKS:
            self.client.post('/tools/workflow_accept_task_result', json={'arguments': {
                'task_id': tid, 'summary': 'done', 'artifacts_changed': [], 'tests_run': [], 'test_results': {}
            }})
        r = self.client.post('/tools/workflow_is_done', json={'arguments': {}})
        self.assertTrue(r.json()['done'])


class TestWorkflowServerResources(unittest.TestCase):

    def setUp(self):
        try:
            os.remove(DB)
        except FileNotFoundError:
            pass
        import orchestrator.workflow_server.app as app_module
        from orchestrator.workflow_server.storage import Storage
        from orchestrator.workflow_server.catalog import Catalog
        from orchestrator.workflow_server.renderers import Renderers
        from orchestrator.workflow_server.engine import WorkflowEngine
        storage = Storage(DB)
        app_module._engine = WorkflowEngine(storage, Catalog(), Renderers(storage))
        self.client = TestClient(app_module.app)

    def tearDown(self):
        try:
            os.remove(DB)
        except FileNotFoundError:
            pass

    def test_resource_constraints(self):
        r = self.client.get('/resources/constraints')
        self.assertEqual(r.status_code, 200)
        self.assertIn('content', r.json())

    def test_resource_spec_current(self):
        r = self.client.get('/resources/spec_current')
        self.assertEqual(r.status_code, 200)

    def test_resource_not_found(self):
        r = self.client.get('/resources/nonexistent')
        self.assertEqual(r.status_code, 404)


if __name__ == '__main__':
    unittest.main()
