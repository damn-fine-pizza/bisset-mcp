"""HTTP client that proxies calls to workflow_server."""
import os
import json
import logging
import httpx

BACKEND_URL = os.environ.get('WORKFLOW_BACKEND_URL', 'http://127.0.0.1:8765')

_client = httpx.Client(base_url=BACKEND_URL, timeout=30.0)
logger = logging.getLogger('mcp-client')


def _truncate(value, max_len=400) -> str:
    s = json.dumps(value, ensure_ascii=False) if not isinstance(value, str) else value
    return s if len(s) <= max_len else s[:max_len] + ' …'


def call_tool(name: str, arguments: dict) -> dict:
    logger.info('→ tool=%s args=%s', name, _truncate(arguments))
    resp = _client.post(f'/tools/{name}', json={'arguments': arguments})
    resp.raise_for_status()
    result = resp.json()
    logger.info('← tool=%s response=%s', name, _truncate(result))
    return result


def get_resource(name: str) -> str:
    logger.info('→ resource=%s', name)
    resp = _client.get(f'/resources/{name}')
    resp.raise_for_status()
    content = resp.json()['content']
    logger.info('← resource=%s (%d chars)', name, len(content))
    return content


def get_prompt(name: str) -> str:
    logger.info('→ prompt=%s', name)
    resp = _client.get(f'/prompts/{name}')
    resp.raise_for_status()
    content = resp.json()['content']
    logger.info('← prompt=%s (%d chars)', name, len(content))
    return content


def health() -> bool:
    try:
        resp = _client.get('/health', timeout=3.0)
        return resp.status_code == 200
    except Exception:
        return False
