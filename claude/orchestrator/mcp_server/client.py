"""HTTP client for Claude MCP - communicates with workflow_server backend.

Tool names from the MCP protocol map 1-to-1 to workflow_server endpoints.
GET-only tools (reads) use GET; everything else uses POST.
Path parameters (session_id, task_id, etc.) are extracted from `arguments`.
"""
import os
import logging
import httpx

BACKEND_URL = os.environ.get('WORKFLOW_BACKEND_URL', 'http://127.0.0.1:8765')

logger = logging.getLogger('claude-mcp-client')

# Tools that use GET (read-only, no body)
_GET_TOOLS = {
    'workflow_detect_session',
    'workflow_list_sessions',
    'workflow_get_session',
    'workflow_next_question',
    'workflow_list_questions',
    'workflow_get_spec',
    'workflow_next_task',
    'workflow_list_proposals',
    'workflow_get_job_status',
    'workflow_list_jobs',
    'workflow_status',
    'workflow_get_events',
}

# Tools whose URL contains path params drawn from arguments
_PATH_PARAM_TOOLS: dict[str, str] = {
    # tool_name → URL template (keys from arguments filled in)
    'workflow_get_session':           '/workflow_get_session/{session_id}',
    'workflow_switch_session':        '/workflow_switch_session',
    'workflow_start_interview':       '/workflow_start_interview/{session_id}',
    'workflow_next_question':         '/workflow_next_question/{session_id}',
    'workflow_record_answer':         '/workflow_record_answer/{session_id}/{question_id}',
    'workflow_list_questions':        '/workflow_list_questions/{session_id}',
    'workflow_freeze_spec':           '/workflow_freeze_spec/{session_id}',
    'workflow_get_spec':              '/workflow_get_spec/{session_id}',
    'workflow_next_task':             '/workflow_next_task/{session_id}',
    'workflow_assign_model':          '/workflow_assign_model/{session_id}/{task_id}',
    'workflow_accept_task_result':    '/workflow_accept_task_result/{session_id}/{task_id}',
    'workflow_add_task':              '/workflow_add_task/{session_id}',
    'workflow_run_tests':             '/workflow_run_tests/{session_id}',
    'workflow_complete_task':         '/workflow_complete_task/{session_id}/{task_id}',
    'workflow_store_proposal':        '/workflow_store_proposal/{session_id}',
    'workflow_list_proposals':        '/workflow_list_proposals/{session_id}',
    'workflow_start_agent':           '/workflow_start_agent/{session_id}',
    'workflow_get_job_status':        '/workflow_get_job_status/{session_id}/{job_id}',
    'workflow_list_jobs':             '/workflow_list_jobs/{session_id}',
    'workflow_status':                '/workflow_status/{session_id}',
    'workflow_get_events':            '/workflow_get_events/{session_id}',
}

# Path params that should NOT be sent as query/body params
_PATH_KEYS = {'session_id', 'task_id', 'question_id', 'job_id'}


def _build_url(tool_name: str, arguments: dict) -> tuple[str, dict]:
    """Return (url, remaining_args) with path params interpolated."""
    template = _PATH_PARAM_TOOLS.get(tool_name, f'/{tool_name}')
    url = template.format(**{k: arguments.get(k, '') for k in _PATH_KEYS})
    remaining = {k: v for k, v in arguments.items() if k not in _PATH_KEYS}
    return url, remaining


def call_tool(name: str, arguments: dict) -> dict:
    """Forward MCP tool call to the workflow_server and return its response."""
    logger.info('→ tool=%s', name)
    url, body = _build_url(name, arguments or {})

    with httpx.Client(base_url=BACKEND_URL, timeout=30.0) as client:
        if name in _GET_TOOLS:
            resp = client.get(url, params=body)
        else:
            resp = client.post(url, params=body)
        resp.raise_for_status()

    result = resp.json()
    logger.info('← tool=%s status=%s', name, resp.status_code)
    return result


def get_prompt(phase_name: str) -> dict:
    """Fetch a phase prompt from the workflow_server."""
    logger.info('→ prompt phase=%s', phase_name)
    with httpx.Client(base_url=BACKEND_URL, timeout=10.0) as client:
        resp = client.get(f'/prompts/phase/{phase_name}')
        resp.raise_for_status()
    return resp.json()


def health() -> bool:
    """Return True if the workflow_server is up and healthy."""
    try:
        with httpx.Client(base_url=BACKEND_URL, timeout=3.0) as client:
            return client.get('/health').status_code == 200
    except Exception:
        return False
