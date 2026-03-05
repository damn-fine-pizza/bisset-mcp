"""
workflow_server — FastAPI backend for the MCP Workflow Orchestrator.

Run with:
    python -m orchestrator.workflow_server
    # or for hot-reload:
    uvicorn orchestrator.workflow_server.app:app --reload --port 8765
"""
import os
import logging
import json
from typing import Any
from fastapi import FastAPI, HTTPException
from pydantic import BaseModel

from .engine import WorkflowEngine
from .storage import Storage
from .catalog import Catalog
from .renderers import Renderers

# Pretty JSON logging (can be disabled with WORKFLOW_PRETTY_JSON_LOGS=0)
class PrettyJSONFormatter(logging.Formatter):
    def format(self, record):
        msg = record.getMessage()
        try:
            parsed = json.loads(msg)
            record.msg = json.dumps(parsed, indent=2, ensure_ascii=False)
            record.args = ()
        except Exception:
            pass
        return super().format(record)

pretty = os.environ.get('WORKFLOW_PRETTY_JSON_LOGS', '1').lower() not in ('0', 'false', 'no')
if pretty:
    handler = logging.StreamHandler()
    handler.setFormatter(PrettyJSONFormatter('%(asctime)s %(levelname)s %(name)s: %(message)s'))
    logging.getLogger().handlers = [handler]
    logging.getLogger().setLevel(logging.INFO)
logger = logging.getLogger('workflow-server')

DB_PATH = os.path.join(os.path.dirname(__file__), 'workflow.db')
RESOURCES_DIR = os.path.join(os.path.dirname(__file__), 'resources')

app = FastAPI(title='Workflow Server', version='1.0.0')

_storage = Storage(DB_PATH)
_catalog = Catalog()
_renderers = Renderers(_storage)
_engine = WorkflowEngine(_storage, _catalog, _renderers)


# ─── Health ──────────────────────────────────────────────────────────────────

@app.get('/health')
def health():
    return {'ok': True}


# ─── Tools ───────────────────────────────────────────────────────────────────

_NO_SESSION_ERROR = {
    'error': 'no_active_session',
    'message': (
        'No session is active. '
        'Call workflow_list_sessions() to see existing sessions, '
        'then workflow_switch_session(session_id) to resume one, '
        'or workflow_new_session() to start a new project.'
    ),
}


def _require_session() -> dict | None:
    """Return an error dict if no session is active, else None."""
    if not _storage._active_session_id:
        return _NO_SESSION_ERROR
    return None


class ToolRequest(BaseModel):
    arguments: dict[str, Any] = {}


@app.post('/tools/workflow_new_session')
def tool_new_session(req: ToolRequest):
    return _engine.new_session(req.arguments.get('name', ''))


@app.post('/tools/workflow_switch_session')
def tool_switch_session(req: ToolRequest):
    session_id = req.arguments.get('session_id', '')
    if not session_id:
        return {'error': 'session_id required'}
    return _engine.switch_session(session_id)


@app.post('/tools/workflow_detect_session')
def tool_detect_session(req: ToolRequest):
    cwd = req.arguments.get('cwd', '')
    if not cwd:
        return {'error': 'cwd required'}
    return _engine.detect_session(cwd)


@app.post('/tools/workflow_list_sessions')
def tool_list_sessions(req: ToolRequest):
    return {'sessions': _engine.list_sessions()}


@app.post('/tools/workflow_list_tasks')
def tool_list_tasks(req: ToolRequest):
    if err := _require_session(): return err
    status_filter = req.arguments.get('status')
    rows = _storage.list_tasks()
    tasks = [{'id': r[0], 'title': r[1], 'status': r[2], 'created_at': r[3], 'done_at': r[4],
               'evidence': r[5], 'description': r[6] or '', 'acceptance_criteria': r[7] or '',
               'negative_acceptance_criteria': r[8] or ''} for r in rows]
    if status_filter:
        tasks = [t for t in tasks if t['status'] == status_filter]
    return {'tasks': tasks}


@app.post('/tools/workflow_add_task')
def tool_add_task(req: ToolRequest):
    if err := _require_session(): return err
    a = req.arguments
    return _engine.add_task(
        a['task_id'],
        a['title'],
        a.get('description', ''),
        a.get('acceptance_criteria', ''),
        a.get('negative_acceptance_criteria', ''),
    )


@app.post('/tools/workflow_list_questions')
def tool_list_questions(req: ToolRequest):
    if err := _require_session(): return err
    answered_filter = req.arguments.get('answered')
    rows = _storage.get_all_answers()
    questions = [{'id': r[0], 'text': r[1], 'answer': r[2]} for r in rows]
    if answered_filter is True:
        questions = [q for q in questions if q['answer'] is not None]
    elif answered_filter is False:
        questions = [q for q in questions if q['answer'] is None]
    return {'questions': questions}


@app.post('/tools/workflow_advance_phase')
def tool_advance_phase(req: ToolRequest):
    if err := _require_session(): return err
    return _engine.advance_phase(req.arguments.get('signal', ''))


@app.post('/tools/workflow_store_proposal')
def tool_store_proposal(req: ToolRequest):
    if err := _require_session(): return err
    a = req.arguments
    return _engine.store_proposal(a.get('paradigm', ''), a.get('content', ''))


@app.post('/tools/workflow_list_proposals')
def tool_list_proposals(req: ToolRequest):
    if err := _require_session(): return err
    return _engine.list_proposals()


@app.post('/tools/workflow_start')
def tool_start(req: ToolRequest):
    # Create a session automatically if none is active to simplify client usage
    if not _storage._active_session_id:
        _engine.new_session('auto')
    return _engine.start(req.arguments.get('project_meta', {}))


@app.post('/tools/workflow_get_state')
def tool_get_state(req: ToolRequest):
    if err := _require_session(): return err
    return _engine.get_state()


@app.post('/tools/workflow_next_question')
def tool_next_question(req: ToolRequest):
    if err := _require_session(): return err
    return _engine.next_question()


@app.post('/tools/workflow_record_answer')
def tool_record_answer(req: ToolRequest):
    if err := _require_session(): return err
    a = req.arguments
    return _engine.record_answer(a['question_id'], a['answer_text'])


@app.post('/tools/workflow_freeze_spec')
def tool_freeze_spec(req: ToolRequest):
    if err := _require_session(): return err
    return _engine.freeze_spec()


@app.post('/tools/workflow_next_task')
def tool_next_task(req: ToolRequest):
    if err := _require_session(): return err
    return _engine.next_task()


@app.post('/tools/workflow_run_tests')
def tool_run_tests(req: ToolRequest):
    if err := _require_session(): return err
    task_id = req.arguments.get('task_id', '')
    if not task_id:
        return {'error': 'task_id required'}
    return _engine.run_tests(task_id)


@app.post('/tools/workflow_accept_task_result')
def tool_accept_task_result(req: ToolRequest):
    if err := _require_session(): return err
    a = req.arguments
    return _engine.accept_task_result(
        a['task_id'],
        a['summary'],
        a.get('artifacts_changed', []),
        a.get('tests_run', []),
        a.get('test_results', {}),
    )


@app.post('/tools/workflow_report')
def tool_report(req: ToolRequest):
    if err := _require_session(): return err
    return _engine.report()


@app.post('/tools/workflow_is_done')
def tool_is_done(req: ToolRequest):
    if err := _require_session(): return err
    return _engine.is_done()


@app.post('/tools/workflow_status')
def tool_status(req: ToolRequest):
    if err := _require_session(): return err
    return _engine.status()


@app.post('/tools/workflow_bootstrap_project')
def tool_bootstrap_project(req: ToolRequest):
    a = req.arguments
    return _engine.bootstrap_project(
        cwd=a.get('cwd', ''),
        autodetect=a.get('autodetect', True),
    )


@app.post('/tools/workflow_run_until_blocked')
def tool_run_until_blocked(req: ToolRequest):
    if err := _require_session(): return err
    a = req.arguments
    return _engine.run_until_blocked(
        max_iterations=int(a.get('max_iterations', 20)),
        max_minutes=float(a.get('max_minutes', 30.0)),
    )


@app.post('/tools/workflow_get_events')
def tool_get_events(req: ToolRequest):
    if err := _require_session(): return err
    a = req.arguments
    return _engine.get_events(limit=int(a.get('limit', 50)))


@app.post('/tools/workflow_store_note')
def tool_store_note(req: ToolRequest):
    if err := _require_session(): return err
    a = req.arguments
    key = a.get('key')
    content = a.get('content', '')
    if not key:
        return {'error': 'key required'}
    return _engine.store_note(key, content)


@app.post('/tools/workflow_tick')
def tool_workflow_tick(req: ToolRequest):
    # workflow_tick is the deterministic driver — returns the single next action
    if not _storage._active_session_id:
        # allow caller to create a session via the driver
        return {'type': 'need_tool', 'reason': 'no_active_session', 'tool': 'workflow_new_session', 'args': {'name': 'auto'}}
    return _engine.workflow_tick()


# ─── Resources ───────────────────────────────────────────────────────────────

@app.get('/resources/{name}')
def get_resource(name: str):
    # Prefer DB-backed resources stored in session meta to avoid filesystem I/O
    if name == 'spec_current':
        v = _storage.read_meta('spec_current') or {}
        content = v.get('content') or ''
        return {'name': name, 'content': content}
    if name == 'plan_workbreakdown':
        v = _storage.read_meta('plan_workbreakdown') or {}
        content = v.get('tasks') or v.get('content') or ''
        return {'name': name, 'content': content}
    if name.startswith('adr:'):
        # name like 'adr:adr-0001'
        v = _storage.read_meta(name)
        content = v.get('content') if v else None
        if content is None:
            raise HTTPException(404, f'resource {name!r} not found')
        return {'name': name, 'content': content}
    if name.startswith('adr:'):
        # name like 'adr:adr-0001'
        v = _storage.read_meta(name)
        content = v.get('content') if v else None
        if content is None:
            raise HTTPException(404, f'resource {name!r} not found')
        return {'name': name, 'content': content}
    # fallback to static constraints file if present on disk
    path = os.path.join(RESOURCES_DIR, f'{name}.json') if name == 'constraints' else None
    if path and os.path.exists(path):
        with open(path) as f:
            return {'name': name, 'content': f.read()}
    raise HTTPException(404, f'resource {name!r} not found')


# ─── Prompts (dynamic — composed from live DB state) ─────────────────────────

@app.get('/prompts/{name:path}')
def get_prompt(name: str):
    content = _build_prompt(name)
    if content is None:
        raise HTTPException(404, f'prompt {name!r} not found')
    return {'name': name, 'content': content}


def _build_prompt(name: str) -> str | None:
    if not _storage._active_session_id:
        return f"# No active session\nCall `workflow_new_session()` then `workflow_start()` to begin."
    answers = {row[0]: (row[1], row[2]) for row in _storage.get_all_answers()}  # qid -> (text, answer)
    meta = _storage.read_meta('project_meta') or {}
    phase = _storage.read_meta('phase') or 'interview'
    project_name = (answers.get('q-001', (None, meta.get('name', 'unknown')))[1]) or meta.get('name', 'unknown')

    if name == 'phases/requirements_interview':
        return _prompt_requirements_interview(answers, phase)
    if name == 'phases/design_review':
        return _prompt_design_review(answers, project_name)
    if name == 'phases/implementation_loop':
        return _prompt_implementation_loop(answers, project_name, phase)
    if name == 'roles/architect':
        return _prompt_role('Architect', project_name, answers, phase,
            'Design system architecture, make technology decisions, write ADRs.')
    if name == 'roles/product_owner':
        return _prompt_role('Product Owner', project_name, answers, phase,
            'Prioritise features, clarify requirements, validate that the spec matches user needs.')
    if name == 'roles/tech_lead':
        return _prompt_role('Tech Lead', project_name, answers, phase,
            'Guide implementation, review code quality, ensure tests pass and CI is green.')
    if name == 'roles/test_engineer':
        return _prompt_role('Test Engineer', project_name, answers, phase,
            'Write and run tests, report coverage, validate acceptance criteria.')
    if name == 'roles/build_engineer':
        return _prompt_role('Build Engineer', project_name, answers, phase,
            'Maintain CI/CD pipelines, Docker/deployment manifests, dependency management.')
    if name == 'roles/requirements_validate':
        return _prompt_requirements_validate(answers)
    return None


def _prompt_requirements_validate(answers: dict) -> str:
    """Produce a strict, machine-parseable validation report.

    Output MUST follow this format exactly:

    DECISION: <requirements_valid|requirements_incomplete>
    CLOSED_QUESTIONS:
    - Q1: ...
    - Q2: ...
    NOTES:
    - ...
    """
    # Simple deterministic validator: if any unanswered question exists, mark incomplete
    unanswered = [qid for qid, (_, ans) in sorted(answers.items()) if not ans]
    if unanswered:
        decision = 'requirements_incomplete'
    else:
        decision = 'requirements_valid'
    lines = [f'DECISION: {decision}', 'CLOSED_QUESTIONS:']
    for qid, (text, ans) in sorted(answers.items()):
        lines.append(f'- {qid}: {text}')
    lines.append('NOTES:')
    if unanswered:
        lines.append('- Some questions are unanswered; re-run the interview to collect missing answers.')
    else:
        lines.append('- All questions answered. Requirements validated.')
    return '\n'.join(lines)



def _qa_block(answers: dict) -> str:
    lines = []
    for qid, (text, answer) in sorted(answers.items()):
        status = answer if answer else '_UNANSWERED_'
        lines.append(f'- **{qid}** {text}\n  → {status}')
    return '\n'.join(lines) if lines else '_(no answers yet)_'


_LANG_RULE = """> **Language rule**: regardless of the conversation language, all text you write
> into Bisset tools (`answer_text`, `summary`, `title`, `description`,
> `acceptance_criteria`, artifact paths, etc.) **must be in English**.
> You may speak to the user in any language, but every value stored in the
> workflow database must be English."""


def _prompt_requirements_interview(answers: dict, phase: str) -> str:
    answered = {k: v for k, v in answers.items() if v[1]}
    unanswered = {k: v for k, v in answers.items() if not v[1]}
    return f"""# Requirements Interview

{_LANG_RULE}

You are conducting a structured requirements interview.

## Your job
1. Call `workflow_next_question()` to get the next question.
2. Present the question clearly to the user.
3. Call `workflow_record_answer(question_id, answer_text)` with their response.
4. Repeat until `next_question` returns `{{"done": true}}`.
5. Then call `workflow_freeze_spec()` to lock the spec and move to execution.

## Current state
- Phase: **{phase}**
- Questions answered: **{len(answered)}/{len(answers)}**

## Answered so far
{_qa_block(answered) if answered else '_(none yet)_'}

## Still pending
{chr(10).join(f'- {qid}: {text}' for qid, (text, _) in sorted(unanswered.items())) if unanswered else '✅ All answered — call `workflow_freeze_spec()` now.'}
"""


def _prompt_design_review(answers: dict, project_name: str) -> str:
    return f"""# Design Review — {project_name}

{_LANG_RULE}

You are reviewing the project specification after the requirements interview.

## Your job
- Identify gaps, contradictions, or risky assumptions in the spec.
- Propose ADR entries for major architectural decisions.
- Confirm the work breakdown is complete and correctly sequenced.
- If changes are needed, call `workflow_record_answer()` to update answers, then call `workflow_freeze_spec()` again.

## Full specification
{_qa_block(answers)}
"""


def _prompt_implementation_loop(answers: dict, project_name: str, phase: str) -> str:
    task = _engine.next_task()
    tasks = _storage.list_tasks()
    done_count = sum(1 for t in tasks if t[2] == 'done')
    total = len(tasks)

    task_section = ''
    if task.get('done'):
        task_section = '✅ **All tasks complete.** Call `workflow_is_done()` to confirm.'
    elif task.get('error'):
        task_section = f'⚠️ {task["error"]}'
    else:
        ac_block = ''
        if task.get('acceptance_criteria'):
            feature_path = _engine._feature_file_path(task['id']) or '(project_path not set)'
            ac_block = (
                f"\n### Acceptance Criteria (Gherkin)\n```gherkin\n{task['acceptance_criteria']}\n```\n"
                f"\n> **Feature file**: `{feature_path}`\n"
                f"> **Required before accepting**: call `workflow_run_tests(\"{task['id']}\")` "
                f"and confirm `ok: true` before calling `workflow_accept_task_result`.\n"
            )
        desc_block = f"\n**Description**: {task['description']}\n" if task.get('description') else ''
        task_section = f"""## Current task
- **ID**: `{task['id']}`
- **Title**: {task['title']}
{desc_block}{ac_block}
## Definition of Done
- Implementation is complete and committed.
- Tests written and passing (BDD scenarios above must pass if acceptance_criteria is set).
- `workflow_accept_task_result(task_id, summary, artifacts_changed, tests_run, test_results)` called with evidence.
"""

    return f"""# Implementation Loop — {project_name}

{_LANG_RULE}

You are implementing the project task by task.

## Your job
1. Call `workflow_next_task()` to get the current task.
2. Implement it fully (write code, tests, docs as needed).
3. Call `workflow_accept_task_result(task_id, summary, artifacts_changed, tests_run, test_results)`.
4. Repeat until `workflow_is_done()` returns `{{"done": true}}`.

## Progress
- Phase: **{phase}**
- Tasks done: **{done_count}/{total}**

{task_section}

## Project context
{_qa_block(answers)}
"""


def _prompt_role(role: str, project_name: str, answers: dict, phase: str, responsibility: str) -> str:
    return f"""# Role: {role} — {project_name}

{_LANG_RULE}

## Responsibility
{responsibility}

## Current state
- Phase: **{phase}**

## Project context
{_qa_block(answers)}
"""
