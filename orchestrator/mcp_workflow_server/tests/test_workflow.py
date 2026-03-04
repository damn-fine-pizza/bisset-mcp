import unittest
import os
from orchestrator.mcp_workflow_server.storage import Storage
from orchestrator.mcp_workflow_server.catalog import Catalog, QUESTIONS, PLAN_TASKS
from orchestrator.mcp_workflow_server.renderers import Renderers
from orchestrator.mcp_workflow_server.engine import WorkflowEngine

DB = '/tmp/test_workflow.db'


def make_engine():
    try:
        os.remove(DB)
    except FileNotFoundError:
        pass
    storage = Storage(DB)
    catalog = Catalog()
    renderers = Renderers(storage)
    return WorkflowEngine(storage, catalog, renderers)


class TestStateTransitions(unittest.TestCase):
    def setUp(self):
        self.engine = make_engine()

    def tearDown(self):
        try:
            os.remove(DB)
        except FileNotFoundError:
            pass

    def test_initial_phase_is_interview(self):
        state = self.engine.get_state()
        self.assertEqual(state['phase'], 'interview')

    def test_start_sets_interview_phase(self):
        self.engine.start({'name': 'proj'})
        state = self.engine.get_state()
        self.assertEqual(state['phase'], 'interview')

    def test_freeze_transitions_to_execution(self):
        self.engine.start({'name': 'proj'})
        self._answer_all()
        self.engine.freeze_spec()
        self.assertEqual(self.engine.phase, 'execution')

    def test_all_tasks_done_transitions_to_done(self):
        self.engine.start({'name': 'proj'})
        self._answer_all()
        self.engine.freeze_spec()
        while True:
            t = self.engine.next_task()
            if t.get('done'):
                break
            self.engine.accept_task_result(t['id'], 'done', [], [], {})
        self.assertEqual(self.engine.phase, 'done')
        self.assertTrue(self.engine.is_done()['done'])

    def _answer_all(self):
        while True:
            q = self.engine.next_question()
            if q.get('done'):
                break
            self.engine.record_answer(q['id'], 'test answer')


class TestQuestionSelection(unittest.TestCase):
    def setUp(self):
        self.engine = make_engine()
        self.engine.start({})

    def tearDown(self):
        try:
            os.remove(DB)
        except FileNotFoundError:
            pass

    def test_questions_returned_in_order(self):
        ids = []
        while True:
            q = self.engine.next_question()
            if q.get('done'):
                break
            ids.append(q['id'])
            self.engine.record_answer(q['id'], 'x')
        expected = [qid for qid, _ in QUESTIONS]
        self.assertEqual(ids, expected)

    def test_next_question_returns_first_unanswered(self):
        q1 = self.engine.next_question()
        self.assertEqual(q1['id'], QUESTIONS[0][0])
        self.engine.record_answer(q1['id'], 'answered')
        q2 = self.engine.next_question()
        self.assertEqual(q2['id'], QUESTIONS[1][0])

    def test_all_answered_returns_done(self):
        for qid, _ in QUESTIONS:
            self.engine.record_answer(qid, 'a')
        q = self.engine.next_question()
        self.assertTrue(q.get('done'))


class TestFreezeSpec(unittest.TestCase):
    def setUp(self):
        self.engine = make_engine()

    def tearDown(self):
        try:
            os.remove(DB)
        except FileNotFoundError:
            pass

    def test_freeze_creates_spec_file(self):
        self.engine.start({'name': 'p'})
        for qid, _ in QUESTIONS:
            self.engine.record_answer(qid, f'answer for {qid}')
        result = self.engine.freeze_spec()
        self.assertTrue(os.path.exists(result['spec_path']))

    def test_spec_contains_answers(self):
        self.engine.start({'name': 'p'})
        self.engine.record_answer('q-001', 'SpecialProjectName')
        result = self.engine.freeze_spec()
        with open(result['spec_path']) as fh:
            content = fh.read()
        self.assertIn('SpecialProjectName', content)

    def test_freeze_creates_tasks_in_storage(self):
        self.engine.start({'name': 'p'})
        self.engine.freeze_spec()
        tasks = self.engine.storage.list_tasks()
        self.assertEqual(len(tasks), len(PLAN_TASKS))

    def test_freeze_deterministic_task_ids(self):
        self.engine.start({'name': 'p'})
        self.engine.freeze_spec()
        tasks = self.engine.storage.list_tasks()
        stored_ids = [t[0] for t in tasks]
        expected_ids = [tid for tid, _ in PLAN_TASKS]
        self.assertEqual(stored_ids, expected_ids)


class TestTaskProgression(unittest.TestCase):
    def setUp(self):
        self.engine = make_engine()
        self.engine.start({'name': 'p'})
        self.engine.freeze_spec()

    def tearDown(self):
        try:
            os.remove(DB)
        except FileNotFoundError:
            pass

    def test_next_task_returns_first_pending(self):
        t = self.engine.next_task()
        self.assertEqual(t['id'], PLAN_TASKS[0][0])

    def test_accept_task_advances_to_next(self):
        t1 = self.engine.next_task()
        self.engine.accept_task_result(t1['id'], 'done', [], [], {})
        t2 = self.engine.next_task()
        self.assertEqual(t2['id'], PLAN_TASKS[1][0])

    def test_next_task_in_interview_phase_returns_error(self):
        eng = make_engine()
        eng.start({})
        result = eng.next_task()
        self.assertIn('error', result)
        try:
            os.remove(DB)
        except FileNotFoundError:
            pass

    def test_complete_all_tasks(self):
        for tid, _ in PLAN_TASKS:
            self.engine.accept_task_result(tid, 'done', [], [], {})
        self.assertTrue(self.engine.is_done()['done'])


if __name__ == '__main__':
    unittest.main()
