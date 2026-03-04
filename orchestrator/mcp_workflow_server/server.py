import os
import logging
from mcp.server.fastmcp import FastMCP
from .engine import WorkflowEngine
from .storage import Storage
from .catalog import Catalog
from .renderers import Renderers

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger('mcp-workflow-server')

DB_PATH = os.path.join(os.path.dirname(__file__), 'workflow.db')
PROMPTS_DIR = os.path.join(os.path.dirname(__file__), 'prompts')
RESOURCES_DIR = os.path.join(os.path.dirname(__file__), 'resources')

mcp = FastMCP('BissetMCP Workflow Orchestrator')

_storage = Storage(DB_PATH)
_catalog = Catalog()
_renderers = Renderers(_storage)
_engine = WorkflowEngine(_storage, _catalog, _renderers)


# ─── Prompts ─────────────────────────────────────────────────────────────────

def _read_prompt(name: str) -> str:
    path = os.path.join(PROMPTS_DIR, name)
    with open(path) as f:
        return f.read()


@mcp.prompt(name='roles/architect')
def prompt_architect(project_name: str = '', constraints: str = '', current_phase: str = '') -> str:
    tmpl = _read_prompt('roles-architect.md')
    return tmpl + f'\n\nproject_name={project_name}\nconstraints={constraints}\ncurrent_phase={current_phase}'


@mcp.prompt(name='roles/product_owner')
def prompt_product_owner(project_name: str = '', business_goals: str = '') -> str:
    tmpl = _read_prompt('roles-product_owner.md')
    return tmpl + f'\n\nproject_name={project_name}\nbusiness_goals={business_goals}'


@mcp.prompt(name='roles/tech_lead')
def prompt_tech_lead(project_name: str = '', tech_stack: str = '') -> str:
    tmpl = _read_prompt('roles-tech_lead.md')
    return tmpl + f'\n\nproject_name={project_name}\ntech_stack={tech_stack}'


@mcp.prompt(name='roles/test_engineer')
def prompt_test_engineer(project_name: str = '', testing_scope: str = '') -> str:
    tmpl = _read_prompt('roles-test_engineer.md')
    return tmpl + f'\n\nproject_name={project_name}\ntesting_scope={testing_scope}'


@mcp.prompt(name='roles/build_engineer')
def prompt_build_engineer(project_name: str = '', ci_constraints: str = '') -> str:
    tmpl = _read_prompt('roles-build_engineer.md')
    return tmpl + f'\n\nproject_name={project_name}\nci_constraints={ci_constraints}'


@mcp.prompt(name='phases/requirements_interview')
def prompt_requirements_interview() -> str:
    return _read_prompt('phases-requirements_interview.md')


@mcp.prompt(name='phases/design_review')
def prompt_design_review() -> str:
    return _read_prompt('phases-design_review.md')


@mcp.prompt(name='phases/implementation_loop')
def prompt_implementation_loop() -> str:
    return _read_prompt('phases-implementation_loop.md')


# ─── Resources ────────────────────────────────────────────────────────────────

@mcp.resource('spec://current')
def resource_spec() -> str:
    path = os.path.join(RESOURCES_DIR, 'spec', 'current.md')
    with open(path) as f:
        return f.read()


@mcp.resource('constraints://current')
def resource_constraints() -> str:
    path = os.path.join(RESOURCES_DIR, 'constraints.json')
    with open(path) as f:
        return f.read()


@mcp.resource('decisions://adr-index')
def resource_adr_index() -> str:
    path = os.path.join(RESOURCES_DIR, 'decisions', 'adr-index.md')
    with open(path) as f:
        return f.read()


@mcp.resource('plan://workbreakdown')
def resource_plan() -> str:
    path = os.path.join(RESOURCES_DIR, 'plan', 'workbreakdown.yaml')
    with open(path) as f:
        return f.read()


# ─── Tools ────────────────────────────────────────────────────────────────────

@mcp.tool()
def workflow_start(project_meta: dict) -> dict:
    """Start a new workflow and seed the question catalog."""
    return _engine.start(project_meta)


@mcp.tool()
def workflow_get_state() -> dict:
    """Return current phase, answer count and task count."""
    return _engine.get_state()


@mcp.tool()
def workflow_next_question() -> dict:
    """Return the next unanswered question, or done:true if complete."""
    return _engine.next_question()


@mcp.tool()
def workflow_record_answer(question_id: str, answer_text: str) -> dict:
    """Record an answer for a question by ID."""
    return _engine.record_answer(question_id, answer_text)


@mcp.tool()
def workflow_freeze_spec() -> dict:
    """Freeze the spec, write ADR stub and work breakdown, transition to execution phase."""
    return _engine.freeze_spec()


@mcp.tool()
def workflow_next_task() -> dict:
    """Return the next pending task, or done:true if all tasks complete."""
    return _engine.next_task()


@mcp.tool()
def workflow_accept_task_result(
    task_id: str,
    summary: str,
    artifacts_changed: list = None,
    tests_run: list = None,
    test_results: dict = None,
) -> dict:
    """Mark a task as done with evidence."""
    return _engine.accept_task_result(
        task_id, summary,
        artifacts_changed or [],
        tests_run or [],
        test_results or {},
    )


@mcp.tool()
def workflow_report() -> dict:
    """Return progress report: phase, answers, tasks."""
    return _engine.report()


@mcp.tool()
def workflow_is_done() -> dict:
    """Return done:true when all tasks are complete."""
    return _engine.is_done()


def main():
    mcp.run(transport='stdio')

