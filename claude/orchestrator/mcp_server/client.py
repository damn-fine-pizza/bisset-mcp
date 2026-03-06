"""HTTP client for Claude MCP - communicates with workflow_server backend."""
import os
import json
import logging
import httpx

BACKEND_URL = os.environ.get('WORKFLOW_BACKEND_URL', 'http://127.0.0.1:8765')
_client = httpx.Client(base_url=BACKEND_URL, timeout=30.0)
logger = logging.getLogger('claude-mcp-client')


def call_tool(name: str, arguments: dict) -> dict:
    """Call a tool on the workflow server."""
    logger.info(f'→ tool={name}')
    resp = _client.post(f'/tools/{name}', json={'arguments': arguments})
    resp.raise_for_status()
    result = resp.json()
    logger.info(f'← tool={name}')
    return result


def get_resource(name: str) -> str:
    """Fetch a resource from the workflow server."""
    logger.info(f'→ resource={name}')
    resp = _client.get(f'/resources/{name}')
    resp.raise_for_status()
    content = resp.json()['content']
    logger.info(f'← resource={name}')
    return content


def get_prompt(name: str) -> str:
    """Fetch a prompt from the workflow server."""
    logger.info(f'→ prompt={name}')
    resp = _client.get(f'/prompts/{name}')
    resp.raise_for_status()
    content = resp.json()['content']
    logger.info(f'← prompt={name}')
    return content


def health() -> bool:
    """Check if workflow server is running."""
    try:
        resp = _client.get('/health', timeout=3.0)
        return resp.status_code == 200
    except Exception:
        return False
