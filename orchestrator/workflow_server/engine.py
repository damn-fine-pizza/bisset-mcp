import time
import os
import re
import subprocess
import logging
from .storage import Storage
from .catalog import Catalog

logger = logging.getLogger('workflow-engine')

# signal → (new_sub_phase, valid_from_sub_phases)
SIGNAL_PHASES = {
    # Phase 2.5 ↔ interview loop
    'requirements_valid':      ('phase_3_architect',      {'phase_2_5_requirements'}),
    'requirements_incomplete': ('phase_2_interview',      {'phase_2_5_requirements'}),
    'interview_updated':       ('phase_2_5_requirements', {'phase_2_interview'}),
    # Phase 3 → 4 → 5 → 6
    'tasks_ready':             ('phase_4_gherkin',        {'phase_3_architect'}),
    'features_written':        ('phase_5_implement',      {'phase_4_gherkin'}),
    'implementation_complete': ('phase_6_coverage',       {'phase_5_implement'}),
    'coverage_passed':         ('done',                   {'phase_6_coverage'}),
    'coverage_failed':         ('phase_5_implement',      {'phase_6_coverage'}),
}


def _parse_bdd_output(output: str) -> tuple[int, int]:
    """Parse passed/failed scenario counts from behave, pytest, or cucumber output."""
    # behave: "3 scenarios passed, 0 failed, 0 skipped"  or  "3 scenarios (3 passed)"
    m = re.search(r'(\d+) scenarios? passed.*?(\d+) failed', output)
    if m:
        return int(m.group(1)), int(m.group(2))
    m = re.search(r'(\d+) scenarios?\s+\((\d+) passed', output)
    if m:
        passed = int(m.group(2))
        total = int(m.group(1))
        return passed, total - passed
    # pytest: "3 passed, 1 failed" or "3 passed"
    passed = failed = 0
    m = re.search(r'(\d+) passed', output)
    if m:
        passed = int(m.group(1))
    m = re.search(r'(\d+) failed', output)
    if m:
        failed = int(m.group(1))
    if passed or failed:
        return passed, failed
    # cucumber: "3 scenarios (1 failed, 2 passed)"
    m = re.search(r'(\d+) scenarios?\s+\(([^)]+)\)', output)
    if m:
        inner = m.group(2)
        p = re.search(r'(\d+) passed', inner)
        f = re.search(r'(\d+) failed', inner)
        return int(p.group(1)) if p else 0, int(f.group(1)) if f else 0
    return 0, 0


def _parse_line_coverage(output: str) -> float | None:
    """Parse TOTAL line coverage % from `coverage report` output."""
    m = re.search(r'^TOTAL\s+\d+\s+\d+.*?(\d+)%\s*$', output, re.MULTILINE)
    if m:
        return float(m.group(1))
    return None

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

    def _get_bdd_config(self) -> dict:
        meta = self.storage.read_meta('project_meta') or {}
        return {
            'project_path': meta.get('project_path', ''),
            'features_dir': meta.get('features_dir', 'features'),
            'test_runner': meta.get('test_runner', 'behave'),
            'test_runner_args': meta.get('test_runner_args', ''),
            'bdd_coverage_threshold': float(meta.get('bdd_coverage_threshold', 80)),
            'use_line_coverage': bool(meta.get('use_line_coverage', False)),
            'line_coverage_threshold': float(meta.get('line_coverage_threshold', 80)),
        }

    def _feature_file_path(self, task_id: str, negative: bool = False) -> str | None:
        cfg = self._get_bdd_config()
        if not cfg['project_path']:
            return None
        suffix = '.negative.feature' if negative else '.feature'
        return os.path.join(cfg['project_path'], cfg['features_dir'], f'{task_id}{suffix}')

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
        sub_phase = self.storage.read_meta('sub_phase')
        row = self.storage.get_session(session_id)
        logger.info('switch_session sid=%s phase=%s sub_phase=%s', session_id, self.phase, sub_phase)
        return {'session_id': row[0], 'name': row[1], 'phase': self.phase, 'sub_phase': sub_phase}

    def list_sessions(self) -> list:
        import json
        rows = self.storage.list_sessions()
        result = []
        for sid, name, created_at, updated_at, phase_raw, sub_phase_raw, tasks_done, tasks_total, q_answered in rows:
            phase = json.loads(phase_raw) if phase_raw else 'not_started'
            sub_phase = json.loads(sub_phase_raw) if sub_phase_raw else None
            result.append({
                'id': sid,
                'name': name,
                'phase': phase,
                'sub_phase': sub_phase,
                'progress': {
                    'tasks_done': tasks_done or 0,
                    'tasks_total': tasks_total or 0,
                    'questions_answered': q_answered or 0,
                },
                'updated_at': updated_at,
                'created_at': created_at,
            })
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
        meta = self.storage.read_meta('project_meta') or {}
        logger.debug('get_state sid=%s phase=%s answers=%d tasks=%d',
                     self._session_id, self.phase, len(answers), len(tasks))
        return {
            'session_id': self._session_id,
            'phase': self.phase,
            'sub_phase': self.storage.read_meta('sub_phase'),
            'answers_count': len(answers),
            'tasks_count': len(tasks),
            'project_meta': meta,
        }

    def next_question(self):
        unanswered = self.storage.list_unanswered()
        if not unanswered:
            logger.info('next_question: all answered')
            return {'done': True, 'message': 'All questions answered'}
        qid, text = unanswered[0]
        logger.info('next_question qid=%s remaining=%d text=%r', qid, len(unanswered), text)
        return {'id': qid, 'text': text}

    def record_answer(self, question_id, answer_text):
        unanswered = {q[0]: q[1] for q in self.storage.list_unanswered()}
        question_text = unanswered.get(question_id, '?')
        self.storage.record_answer(question_id, answer_text)
        logger.info('record_answer qid=%s question=%r answer=%r', question_id, question_text, answer_text[:120] if answer_text else '')
        return {'ok': True, 'question_id': question_id}

    def advance_phase(self, signal: str) -> dict:
        if not self._session_id:
            return {'error': 'No active session'}
        if signal not in SIGNAL_PHASES:
            return {'error': f'Unknown signal {signal!r}. Valid: {sorted(SIGNAL_PHASES)}'}
        new_sub_phase, valid_from = SIGNAL_PHASES[signal]
        current = self.storage.read_meta('sub_phase')
        if current not in valid_from:
            return {'error': f'Signal {signal!r} not valid from sub_phase={current!r}. Expected one of {sorted(valid_from)}'}
        self.storage.write_meta('sub_phase', new_sub_phase)
        if new_sub_phase == 'done':
            self.storage.write_meta('phase', 'done')
            self.phase = 'done'
        logger.info('advance_phase signal=%s %s→%s', signal, current, new_sub_phase)
        return {'ok': True, 'signal': signal, 'sub_phase': new_sub_phase}

    def store_proposal(self, paradigm: str, content: str) -> dict:
        if not self._session_id:
            return {'error': 'No active session'}
        proposal_id = self.storage.add_proposal(paradigm, content)
        logger.info('store_proposal paradigm=%r id=%s', paradigm, proposal_id)
        return {'ok': True, 'paradigm': paradigm, 'proposal_id': proposal_id}

    def list_proposals(self) -> dict:
        if not self._session_id:
            return {'proposals': []}
        rows = self.storage.list_proposals()
        return {'proposals': [{'paradigm': r[0], 'content': r[1], 'created_at': r[2]} for r in rows]}

    def freeze_spec(self):
        answers = self.storage.get_all_answers()
        spec_path = self.renderers.render_spec(answers)
        self.renderers.write_adr_stub('Initial decisions')
        tasks = self.catalog.default_tasks()
        self.renderers.write_plan(tasks)
        self.storage.create_tasks(tasks)
        self.storage.write_meta('phase', 'execution')
        self.storage.write_meta('sub_phase', 'phase_2_5_requirements')
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

    def add_task(self, task_id: str, title: str, description: str = '', acceptance_criteria: str = '', negative_acceptance_criteria: str = '') -> dict:
        if not self._session_id:
            return {'error': 'No active session'}
        self.storage.add_task(task_id, title, description, acceptance_criteria, negative_acceptance_criteria)
        # if workflow was done, new task reopens execution
        if self.phase == 'done':
            self.storage.write_meta('phase', 'execution')
            self.phase = 'execution'
        feature_path = None
        if acceptance_criteria:
            path = self._feature_file_path(task_id)
            if path:
                os.makedirs(os.path.dirname(path), exist_ok=True)
                with open(path, 'w') as f:
                    f.write(f'# Generated by Bisset for task: {task_id}\n')
                    f.write(acceptance_criteria.strip() + '\n')
                feature_path = path
                logger.info('add_task wrote feature file %s', path)
        negative_feature_path = None
        if negative_acceptance_criteria:
            neg_path = self._feature_file_path(task_id, negative=True)
            if neg_path:
                os.makedirs(os.path.dirname(neg_path), exist_ok=True)
                with open(neg_path, 'w') as f:
                    f.write(f'# Generated by Bisset for task: {task_id} (negative cases)\n')
                    f.write(negative_acceptance_criteria.strip() + '\n')
                negative_feature_path = neg_path
                logger.info('add_task wrote negative feature file %s', neg_path)
        logger.info('add_task tid=%s title=%r feature_path=%s neg_feature_path=%s', task_id, title, feature_path, negative_feature_path)
        return {'ok': True, 'task_id': task_id, 'feature_path': feature_path, 'negative_feature_path': negative_feature_path}

    def accept_task_result(self, task_id, summary, artifacts_changed, tests_run, test_results):
        row = self.storage.get_task(task_id)
        if row:
            _, _, _, _, acceptance_criteria, _ = row
            if acceptance_criteria:
                passing_run = self.storage.get_last_passing_run(task_id)
                if not passing_run:
                    logger.warning('accept_task_result blocked: task %s has acceptance_criteria but no passing test run found', task_id)
                    return {
                        'error': (
                            f'Task {task_id!r} has acceptance_criteria — call '
                            f'`workflow_run_tests("{task_id}")` first and ensure all scenarios pass.'
                        )
                    }
                _, passed, failed, total, coverage_pct, line_coverage_pct, _ = passing_run
                cfg = self._get_bdd_config()
                threshold = cfg['bdd_coverage_threshold']
                if coverage_pct < threshold:
                    logger.warning('accept_task_result blocked: task %s coverage %.1f%% < threshold %.1f%%', task_id, coverage_pct, threshold)
                    return {
                        'error': (
                            f'Task {task_id!r} BDD scenario coverage {coverage_pct:.1f}% is below threshold {threshold:.0f}%. '
                            f'Fix failing scenarios and run `workflow_run_tests("{task_id}")` again.'
                        )
                    }
                if cfg['use_line_coverage'] and line_coverage_pct is not None:
                    line_threshold = cfg['line_coverage_threshold']
                    if line_coverage_pct < line_threshold:
                        logger.warning('accept_task_result blocked: task %s line coverage %.1f%% < threshold %.1f%%', task_id, line_coverage_pct, line_threshold)
                        return {
                            'error': (
                                f'Task {task_id!r} line coverage {line_coverage_pct:.1f}% is below threshold {line_threshold:.0f}%. '
                                f'Add more scenarios to cover untested branches and run `workflow_run_tests("{task_id}")` again.'
                            )
                        }
        evidence = {'summary': summary, 'artifacts': artifacts_changed, 'tests_run': tests_run, 'test_results': test_results, 'ts': time.time()}
        self.storage.accept_task(task_id, evidence)
        all_done = self.storage.all_tasks_done()
        if all_done:
            self.storage.write_meta('phase', 'done')
            self.phase = 'done'
        logger.info('accept_task_result tid=%s artifacts=%d tests=%d all_done=%s',
                    task_id, len(artifacts_changed or []), len(tests_run or []), all_done)
        return {'ok': True, 'task_id': task_id}

    def run_tests(self, task_id: str) -> dict:
        if not self._session_id:
            return {'error': 'No active session'}
        row = self.storage.get_task(task_id)
        if not row:
            return {'error': f'Task {task_id!r} not found'}
        cfg = self._get_bdd_config()
        if not cfg['project_path']:
            return {'error': 'project_path not set in project_meta — cannot run tests'}
        feature_path = self._feature_file_path(task_id)
        if not feature_path or not os.path.exists(feature_path):
            return {'error': f'Feature file not found: {feature_path}'}
        cmd = [cfg['test_runner']]
        if cfg['test_runner_args']:
            cmd += cfg['test_runner_args'].split()
        cmd.append(feature_path)
        # include negative feature file if it exists
        neg_path = self._feature_file_path(task_id, negative=True)
        if neg_path and os.path.exists(neg_path):
            cmd.append(neg_path)
            logger.info('run_tests including negative feature file %s', neg_path)
        # wrap with coverage.py if requested
        if cfg['use_line_coverage']:
            cmd = ['coverage', 'run', '--branch', '-m'] + cmd
        logger.info('run_tests tid=%s cmd=%r', task_id, cmd)
        try:
            result = subprocess.run(cmd, capture_output=True, text=True, timeout=300,
                                    cwd=cfg['project_path'])
            output = result.stdout + result.stderr
        except FileNotFoundError:
            return {'error': f'Test runner {cfg["test_runner"]!r} not found — is it installed?'}
        except subprocess.TimeoutExpired:
            return {'error': 'Test run timed out after 300s'}
        passed, failed = _parse_bdd_output(output)
        total = passed + failed
        coverage_pct = (passed / total * 100) if total > 0 else 0.0
        threshold = cfg['bdd_coverage_threshold']
        # optionally wrap with coverage.py for line coverage
        line_coverage_pct = None
        if cfg['use_line_coverage']:
            try:
                cov_result = subprocess.run(
                    ['coverage', 'report'],
                    capture_output=True, text=True, timeout=60,
                    cwd=cfg['project_path'],
                )
                line_coverage_pct = _parse_line_coverage(cov_result.stdout + cov_result.stderr)
                if line_coverage_pct is not None:
                    logger.info('run_tests line coverage %.1f%%', line_coverage_pct)
                else:
                    logger.warning('run_tests: could not parse line coverage from coverage report output')
            except FileNotFoundError:
                logger.warning('run_tests: coverage tool not found — install with: pip install coverage')
            except subprocess.TimeoutExpired:
                logger.warning('run_tests: coverage report timed out')
        line_threshold = cfg['line_coverage_threshold']
        ok = coverage_pct >= threshold and (
            not cfg['use_line_coverage'] or line_coverage_pct is None or line_coverage_pct >= line_threshold
        )
        run_id = self.storage.save_test_run(task_id, passed, failed, coverage_pct, ok, output[-4000:], line_coverage_pct)
        logger.info('run_tests tid=%s passed=%d failed=%d coverage=%.1f%% line_cov=%s ok=%s run_id=%s',
                    task_id, passed, failed, coverage_pct, line_coverage_pct, ok, run_id)
        result_dict = {
            'ok': ok,
            'task_id': task_id,
            'run_id': run_id,
            'passed': passed,
            'failed': failed,
            'total': total,
            'coverage_pct': round(coverage_pct, 1),
            'threshold': threshold,
            'output': output[-2000:],
        }
        if line_coverage_pct is not None:
            result_dict['line_coverage_pct'] = round(line_coverage_pct, 1)
            result_dict['line_coverage_threshold'] = line_threshold
        return result_dict

    def report(self):
        tasks = self.storage.list_tasks()
        answers = self.storage.get_all_answers()
        logger.debug('report phase=%s answers=%d tasks=%d', self.phase, len(answers), len(tasks))
        return {'phase': self.phase, 'answers': len(answers), 'tasks': len(tasks)}

    def is_done(self):
        logger.debug('is_done phase=%s', self.phase)
        return {'done': self.phase == 'done'}
