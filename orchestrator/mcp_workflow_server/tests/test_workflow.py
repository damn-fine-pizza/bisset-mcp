import unittest
import os
from orchestrator.mcp_workflow_server.storage import Storage
from orchestrator.mcp_workflow_server.catalog import Catalog
from orchestrator.mcp_workflow_server.renderers import Renderers
from orchestrator.mcp_workflow_server.engine import WorkflowEngine

class WorkflowTests(unittest.TestCase):
    def setUp(self):
        self.db = '/tmp/test_workflow.db'
        try:
            os.remove(self.db)
        except Exception:
            pass
        self.storage = Storage(self.db)
        self.catalog = Catalog()
        self.renderers = Renderers(self.storage)
        self.engine = WorkflowEngine(self.storage, self.catalog, self.renderers)

    def test_question_flow_and_freeze(self):
        self.engine.start({'name':'testproj'})
        q = self.engine.next_question()
        self.assertIn('id', q)
        # answer all
        while True:
            q = self.engine.next_question()
            if q.get('done'):
                break
            self.engine.record_answer(q['id'], 'ans')
        res = self.engine.freeze_spec()
        self.assertTrue(os.path.exists(res['spec_path']))
        # next tasks
        t = self.engine.next_task()
        self.assertIn('id', t)

    def tearDown(self):
        try:
            os.remove(self.db)
        except Exception:
            pass

if __name__ == '__main__':
    unittest.main()
