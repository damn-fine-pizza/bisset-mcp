import time
from .storage import Storage
from .catalog import Catalog

class WorkflowEngine:
    def __init__(self, storage: Storage, catalog: Catalog, renderers):
        self.storage = storage
        self.catalog = catalog
        self.renderers = renderers
        # phase: interview | execution | done
        meta = self.storage.read_meta('phase')
        self.phase = meta or 'interview'

    def start(self, project_meta=None):
        project_meta = project_meta or {}
        self.storage.write_meta('project_meta', project_meta)
        # populate questions deterministically
        qs = self.catalog.questions()
        self.storage.add_questions(qs)
        self.storage.write_meta('phase', 'interview')
        self.phase = 'interview'
        return {'status':'started', 'project_meta': project_meta}

    def get_state(self):
        answers = self.storage.get_all_answers()
        tasks = self.storage.list_tasks()
        return {'phase': self.phase, 'answers_count': len(answers), 'tasks_count': len(tasks)}

    def next_question(self):
        unanswered = self.storage.list_unanswered()
        if not unanswered:
            return {'done': True, 'message': 'All questions answered'}
        qid, text = unanswered[0]
        return {'id': qid, 'text': text}

    def record_answer(self, question_id, answer_text):
        self.storage.record_answer(question_id, answer_text)
        return {'ok': True, 'question_id': question_id}

    def freeze_spec(self):
        # only allowed after interview
        answers = self.storage.get_all_answers()
        spec_path = self.renderers.render_spec(answers)
        # create ADR stub for any unanswered architecture questions deterministically
        self.renderers.write_adr_stub('Initial decisions')
        # write plan
        tasks = self.catalog.default_tasks()
        self.renderers.write_plan(tasks)
        # create tasks in storage
        self.storage.create_tasks(tasks)
        self.storage.write_meta('phase', 'execution')
        self.phase = 'execution'
        return {'spec_path': spec_path}

    def next_task(self):
        if self.phase != 'execution':
            return {'error': 'not in execution phase'}
        t = self.storage.next_pending_task()
        if not t:
            return {'done': True, 'message': 'All tasks complete or none pending'}
        tid, title = t
        return {'id': tid, 'title': title}

    def accept_task_result(self, task_id, summary, artifacts_changed, tests_run, test_results):
        evidence = {'summary': summary, 'artifacts': artifacts_changed, 'tests_run': tests_run, 'test_results': test_results, 'ts': time.time()}
        self.storage.accept_task(task_id, evidence)
        if self.storage.all_tasks_done():
            self.storage.write_meta('phase', 'done')
            self.phase = 'done'
        return {'ok': True, 'task_id': task_id}

    def report(self):
        tasks = self.storage.list_tasks()
        answers = self.storage.get_all_answers()
        return {'phase': self.phase, 'answers': len(answers), 'tasks': len(tasks)}

    def is_done(self):
        return {'done': self.phase == 'done'}
