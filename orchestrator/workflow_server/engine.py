import time
import logging
from .storage import Storage
from .catalog import Catalog

logger = logging.getLogger('workflow-engine')

class WorkflowEngine:
    def __init__(self, storage: Storage, catalog: Catalog, renderers):
        self.storage = storage
        self.catalog = catalog
        self.renderers = renderers
        self.phase = 'interview'

    @property
    def _session_id(self):
        return self.storage._active_session_id

    def _load_phase(self):
        self.phase = self.storage.read_meta('phase') or 'interview'

    # ── session management ────────────────────────────────────────────────────

    def new_session(self, name: str = '') -> dict:
        sid = self.storage.create_session(name)
        self.phase = 'interview'
        logger.info('new_session sid=%s name=%r', sid, name or sid)
        return {'session_id': sid, 'name': name or sid}

    def switch_session(self, session_id: str) -> dict:
        ok = self.storage.set_active_session(session_id)
        if not ok:
            logger.warning('switch_session: session %r not found', session_id)
            return {'error': f'session {session_id!r} not found'}
        self._load_phase()
        row = self.storage.get_session(session_id)
        logger.info('switch_session sid=%s phase=%s', session_id, self.phase)
        return {'session_id': row[0], 'name': row[1], 'phase': self.phase}

    def list_sessions(self) -> list:
        rows = self.storage.list_sessions()
        result = []
        for sid, name, created_at, updated_at in rows:
            result.append({'id': sid, 'name': name, 'created_at': created_at, 'updated_at': updated_at})
        logger.debug('list_sessions count=%d', len(result))
        return result

    # ── workflow ──────────────────────────────────────────────────────────────

    def start(self, project_meta=None):
        if not self._session_id:
            logger.warning('start: no active session')
            return {'error': 'No active session. Call workflow_new_session first.'}
        project_meta = project_meta or {}
        self.storage.write_meta('project_meta', project_meta)
        qs = self.catalog.questions()
        self.storage.add_questions(qs)
        self.storage.write_meta('phase', 'interview')
        self.phase = 'interview'
        logger.info('start sid=%s questions=%d meta=%r', self._session_id, len(qs), project_meta)
        return {'status': 'started', 'session_id': self._session_id, 'project_meta': project_meta}

    def get_state(self):
        if not self._session_id:
            return {'error': 'No active session'}
        answers = self.storage.get_all_answers()
        tasks = self.storage.list_tasks()
        logger.debug('get_state sid=%s phase=%s answers=%d tasks=%d',
                     self._session_id, self.phase, len(answers), len(tasks))
        return {'session_id': self._session_id, 'phase': self.phase, 'answers_count': len(answers), 'tasks_count': len(tasks)}

    def next_question(self):
        unanswered = self.storage.list_unanswered()
        if not unanswered:
            logger.info('next_question: all answered')
            return {'done': True, 'message': 'All questions answered'}
        qid, text = unanswered[0]
        logger.info('next_question qid=%s remaining=%d', qid, len(unanswered))
        return {'id': qid, 'text': text}

    def record_answer(self, question_id, answer_text):
        self.storage.record_answer(question_id, answer_text)
        logger.info('record_answer qid=%s answer=%r', question_id, answer_text[:80] if answer_text else '')
        return {'ok': True, 'question_id': question_id}

    def freeze_spec(self):
        answers = self.storage.get_all_answers()
        spec_path = self.renderers.render_spec(answers)
        self.renderers.write_adr_stub('Initial decisions')
        tasks = self.catalog.default_tasks()
        self.renderers.write_plan(tasks)
        self.storage.create_tasks(tasks)
        self.storage.write_meta('phase', 'execution')
        self.phase = 'execution'
        logger.info('freeze_spec spec=%s tasks=%d', spec_path, len(tasks))
        return {'spec_path': spec_path}

    def next_task(self):
        if self.phase == 'done':
            logger.info('next_task: workflow already done')
            return {'done': True, 'message': 'All tasks complete'}
        if self.phase != 'execution':
            logger.warning('next_task: wrong phase=%s', self.phase)
            return {'error': 'not in execution phase'}
        t = self.storage.next_pending_task()
        if not t:
            logger.info('next_task: no more pending tasks')
            return {'done': True, 'message': 'All tasks complete or none pending'}
        tid, title, description, acceptance_criteria = t
        logger.info('next_task tid=%s title=%r', tid, title)
        return {'id': tid, 'title': title, 'description': description or '', 'acceptance_criteria': acceptance_criteria or ''}

    def add_task(self, task_id: str, title: str, description: str = '', acceptance_criteria: str = '') -> dict:
        if not self._session_id:
            return {'error': 'No active session'}
        self.storage.add_task(task_id, title, description, acceptance_criteria)
        # if workflow was done, new task reopens execution
        if self.phase == 'done':
            self.storage.write_meta('phase', 'execution')
            self.phase = 'execution'
        logger.info('add_task tid=%s title=%r', task_id, title)
        return {'ok': True, 'task_id': task_id}

    def accept_task_result(self, task_id, summary, artifacts_changed, tests_run, test_results):
        evidence = {'summary': summary, 'artifacts': artifacts_changed, 'tests_run': tests_run, 'test_results': test_results, 'ts': time.time()}
        self.storage.accept_task(task_id, evidence)
        all_done = self.storage.all_tasks_done()
        if all_done:
            self.storage.write_meta('phase', 'done')
            self.phase = 'done'
        logger.info('accept_task_result tid=%s artifacts=%d tests=%d all_done=%s',
                    task_id, len(artifacts_changed or []), len(tests_run or []), all_done)
        return {'ok': True, 'task_id': task_id}

    def report(self):
        tasks = self.storage.list_tasks()
        answers = self.storage.get_all_answers()
        logger.debug('report phase=%s answers=%d tasks=%d', self.phase, len(answers), len(tasks))
        return {'phase': self.phase, 'answers': len(answers), 'tasks': len(tasks)}

    def is_done(self):
        logger.debug('is_done phase=%s', self.phase)
        return {'done': self.phase == 'done'}
