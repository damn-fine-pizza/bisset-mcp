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

mcp = FastMCP('BissetMCP Workflow Orchestrator')


# ─── Prompts (dynamic — fetched from workflow_server) ────────────────────────

@mcp.prompt(name='phases/requirements_interview')
def prompt_requirements_interview() -> str:
    """Current interview state: answered questions, pending questions, next action."""
    return client.get_prompt('phases/requirements_interview')


@mcp.prompt(name='phases/design_review')
def prompt_design_review() -> str:
    """Full spec for review after interview freeze."""
    return client.get_prompt('phases/design_review')


@mcp.prompt(name='phases/implementation_loop')
def prompt_implementation_loop() -> str:
    """Current task + full project context for implementation."""
    return client.get_prompt('phases/implementation_loop')


@mcp.prompt(name='roles/architect')
def prompt_architect() -> str:
    """Architect role with live project context."""
    return client.get_prompt('roles/architect')


@mcp.prompt(name='roles/product_owner')
def prompt_product_owner() -> str:
    """Product Owner role with live project context."""
    return client.get_prompt('roles/product_owner')


@mcp.prompt(name='roles/tech_lead')
def prompt_tech_lead() -> str:
    """Tech Lead role with live project context."""
    return client.get_prompt('roles/tech_lead')


@mcp.prompt(name='roles/test_engineer')
def prompt_test_engineer() -> str:
    """Test Engineer role with live project context."""
    return client.get_prompt('roles/test_engineer')


@mcp.prompt(name='roles/build_engineer')
def prompt_build_engineer() -> str:
    """Build Engineer role with live project context."""
    return client.get_prompt('roles/build_engineer')


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
def workflow_new_session(name: str = '') -> dict:
    """Create a new Bisset project session. Returns a session_id. Must be called before workflow_start."""
    return client.call_tool('workflow_new_session', {'name': name})


@mcp.tool()
def workflow_switch_session(session_id: str) -> dict:
    """Switch to an existing Bisset session by its session_id."""
    return client.call_tool('workflow_switch_session', {'session_id': session_id})


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


@mcp.tool()
def workflow_list_sessions() -> dict:
    """List all sessions (id, name, created_at, updated_at) — read-only."""
    return client.call_tool('workflow_list_sessions', {})


@mcp.tool()
def workflow_list_tasks(status: str = None) -> dict:
    """List all tasks with their status. Optional status filter: 'pending' or 'done'."""
    return client.call_tool('workflow_list_tasks', {'status': status})


@mcp.tool()
def workflow_list_questions(answered: bool = None) -> dict:
    """List all questions with answers. Optional filter: True=answered only, False=unanswered only."""
    return client.call_tool('workflow_list_questions', {'answered': answered})


@mcp.tool()
def workflow_add_task(task_id: str, title: str, description: str = '', acceptance_criteria: str = '') -> dict:
    """Add a project-specific task with optional Gherkin acceptance criteria.
    Call this after workflow_freeze_spec to replace or augment generic tasks with tasks
    tailored to the actual project. acceptance_criteria should be Gherkin Given/When/Then text."""
    return client.call_tool('workflow_add_task', {
        'task_id': task_id,
        'title': title,
        'description': description,
        'acceptance_criteria': acceptance_criteria,
    })


def main():
    if not client.health():
        logger.warning(
            'workflow_server not reachable at %s — start it first with: '
            'python -m orchestrator.workflow_server',
            os.environ.get('WORKFLOW_BACKEND_URL', 'http://127.0.0.1:8765'),
        )
    mcp.run(transport='stdio')
