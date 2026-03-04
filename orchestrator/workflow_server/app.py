"""
workflow_server — FastAPI backend for the MCP Workflow Orchestrator.

Run with:
    python -m orchestrator.workflow_server
    # or for hot-reload:
    uvicorn orchestrator.workflow_server.app:app --reload --port 8765
"""
import os
import logging
from typing import Any
from fastapi import FastAPI, HTTPException
from pydantic import BaseModel

from .engine import WorkflowEngine
from .storage import Storage
from .catalog import Catalog
from .renderers import Renderers

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger('workflow-server')

DB_PATH = os.path.join(os.path.dirname(__file__), 'workflow.db')
RESOURCES_DIR = os.path.join(os.path.dirname(__file__), 'resources')
PROMPTS_DIR = os.path.join(os.path.dirname(__file__), '..', 'mcp_server', 'prompts')

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

class ToolRequest(BaseModel):
    arguments: dict[str, Any] = {}


@app.post('/tools/workflow_start')
def tool_start(req: ToolRequest):
    return _engine.start(req.arguments.get('project_meta', {}))


@app.post('/tools/workflow_get_state')
def tool_get_state(req: ToolRequest):
    return _engine.get_state()


@app.post('/tools/workflow_next_question')
def tool_next_question(req: ToolRequest):
    return _engine.next_question()


@app.post('/tools/workflow_record_answer')
def tool_record_answer(req: ToolRequest):
    a = req.arguments
    return _engine.record_answer(a['question_id'], a['answer_text'])


@app.post('/tools/workflow_freeze_spec')
def tool_freeze_spec(req: ToolRequest):
    return _engine.freeze_spec()


@app.post('/tools/workflow_next_task')
def tool_next_task(req: ToolRequest):
    return _engine.next_task()


@app.post('/tools/workflow_accept_task_result')
def tool_accept_task_result(req: ToolRequest):
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
    return _engine.report()


@app.post('/tools/workflow_is_done')
def tool_is_done(req: ToolRequest):
    return _engine.is_done()


# ─── Resources ───────────────────────────────────────────────────────────────

RESOURCE_FILES = {
    'spec_current':       os.path.join(RESOURCES_DIR, 'spec', 'current.md'),
    'constraints':        os.path.join(RESOURCES_DIR, 'constraints.json'),
    'adr_index':          os.path.join(RESOURCES_DIR, 'decisions', 'adr-index.md'),
    'plan_workbreakdown': os.path.join(RESOURCES_DIR, 'plan', 'workbreakdown.yaml'),
}


@app.get('/resources/{name}')
def get_resource(name: str):
    path = RESOURCE_FILES.get(name)
    if not path or not os.path.exists(path):
        raise HTTPException(404, f'resource {name!r} not found')
    with open(path) as f:
        return {'name': name, 'content': f.read()}


# ─── Prompts ─────────────────────────────────────────────────────────────────

@app.get('/prompts/{name:path}')
def get_prompt(name: str, **kwargs):
    safe = name.replace('/', os.sep)
    path = os.path.join(PROMPTS_DIR, f'{safe.replace(os.sep, "-")}.md')
    if not os.path.exists(path):
        raise HTTPException(404, f'prompt {name!r} not found')
    with open(path) as f:
        return {'name': name, 'content': f.read()}
