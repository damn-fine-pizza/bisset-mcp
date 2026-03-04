"""
mcp_server — thin FastMCP STDIO proxy to workflow_server.

Stays alive as long as Copilot CLI is connected.
The workflow_server backend can be restarted independently.

Run:
    python -m orchestrator.mcp_server

Requires workflow_server to be running at WORKFLOW_BACKEND_URL (default http://127.0.0.1:8765).
"""
import os
import logging
from mcp.server.fastmcp import FastMCP
from . import client

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger('mcp-server')

PROMPTS_DIR = os.path.join(os.path.dirname(__file__), 'prompts')

mcp = FastMCP('BissetMCP Workflow Orchestrator')


# ─── Prompts ─────────────────────────────────────────────────────────────────

def _local_prompt(filename: str) -> str:
    with open(os.path.join(PROMPTS_DIR, filename)) as f:
        return f.read()


@mcp.prompt(name='roles/architect')
def prompt_architect(project_name: str = '', constraints: str = '', current_phase: str = '') -> str:
    tmpl = _local_prompt('roles-architect.md')
    return tmpl + f'\n\nproject_name={project_name}\nconstraints={constraints}\ncurrent_phase={current_phase}'


@mcp.prompt(name='roles/product_owner')
def prompt_product_owner(project_name: str = '', business_goals: str = '') -> str:
    tmpl = _local_prompt('roles-product_owner.md')
    return tmpl + f'\n\nproject_name={project_name}\nbusiness_goals={business_goals}'


@mcp.prompt(name='roles/tech_lead')
def prompt_tech_lead(project_name: str = '', tech_stack: str = '') -> str:
    tmpl = _local_prompt('roles-tech_lead.md')
    return tmpl + f'\n\nproject_name={project_name}\ntech_stack={tech_stack}'


@mcp.prompt(name='roles/test_engineer')
def prompt_test_engineer(project_name: str = '', testing_scope: str = '') -> str:
    tmpl = _local_prompt('roles-test_engineer.md')
    return tmpl + f'\n\nproject_name={project_name}\ntesting_scope={testing_scope}'


@mcp.prompt(name='roles/build_engineer')
def prompt_build_engineer(project_name: str = '', ci_constraints: str = '') -> str:
    tmpl = _local_prompt('roles-build_engineer.md')
    return tmpl + f'\n\nproject_name={project_name}\nci_constraints={ci_constraints}'


@mcp.prompt(name='phases/requirements_interview')
def prompt_requirements_interview() -> str:
    return _local_prompt('phases-requirements_interview.md')


@mcp.prompt(name='phases/design_review')
def prompt_design_review() -> str:
    return _local_prompt('phases-design_review.md')


@mcp.prompt(name='phases/implementation_loop')
def prompt_implementation_loop() -> str:
    return _local_prompt('phases-implementation_loop.md')


# ─── Resources (proxied from workflow_server) ─────────────────────────────────

@mcp.resource('spec://current')
def resource_spec() -> str:
    return client.get_resource('spec_current')


@mcp.resource('constraints://current')
def resource_constraints() -> str:
    return client.get_resource('constraints')


@mcp.resource('decisions://adr-index')
def resource_adr_index() -> str:
    return client.get_resource('adr_index')


@mcp.resource('plan://workbreakdown')
def resource_plan() -> str:
    return client.get_resource('plan_workbreakdown')


# ─── Tools (all proxied to workflow_server) ───────────────────────────────────

@mcp.tool()
def workflow_start(project_meta: dict) -> dict:
    """Start a new workflow and seed the question catalog."""
    return client.call_tool('workflow_start', {'project_meta': project_meta})


@mcp.tool()
def workflow_get_state() -> dict:
    """Return current phase, answer count and task count."""
    return client.call_tool('workflow_get_state', {})


@mcp.tool()
def workflow_next_question() -> dict:
    """Return the next unanswered question, or done:true if complete."""
    return client.call_tool('workflow_next_question', {})


@mcp.tool()
def workflow_record_answer(question_id: str, answer_text: str) -> dict:
    """Record an answer for a question by ID."""
    return client.call_tool('workflow_record_answer', {'question_id': question_id, 'answer_text': answer_text})


@mcp.tool()
def workflow_freeze_spec() -> dict:
    """Freeze the spec, write ADR stub and work breakdown, transition to execution phase."""
    return client.call_tool('workflow_freeze_spec', {})


@mcp.tool()
def workflow_next_task() -> dict:
    """Return the next pending task, or done:true if all tasks complete."""
    return client.call_tool('workflow_next_task', {})


@mcp.tool()
def workflow_accept_task_result(
    task_id: str,
    summary: str,
    artifacts_changed: list = None,
    tests_run: list = None,
    test_results: dict = None,
) -> dict:
    """Mark a task as done with evidence."""
    return client.call_tool('workflow_accept_task_result', {
        'task_id': task_id,
        'summary': summary,
        'artifacts_changed': artifacts_changed or [],
        'tests_run': tests_run or [],
        'test_results': test_results or {},
    })


@mcp.tool()
def workflow_report() -> dict:
    """Return progress report: phase, answers, tasks."""
    return client.call_tool('workflow_report', {})


@mcp.tool()
def workflow_is_done() -> dict:
    """Return done:true when all tasks are complete."""
    return client.call_tool('workflow_is_done', {})


def main():
    if not client.health():
        logger.warning(
            'workflow_server not reachable at %s — start it first with: '
            'python -m orchestrator.workflow_server',
            os.environ.get('WORKFLOW_BACKEND_URL', 'http://127.0.0.1:8765'),
        )
    mcp.run(transport='stdio')
