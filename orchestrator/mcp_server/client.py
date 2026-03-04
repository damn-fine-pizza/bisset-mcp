"""HTTP client that proxies calls to workflow_server."""
import os
import httpx

BACKEND_URL = os.environ.get('WORKFLOW_BACKEND_URL', 'http://127.0.0.1:8765')

_client = httpx.Client(base_url=BACKEND_URL, timeout=30.0)


def call_tool(name: str, arguments: dict) -> dict:
    resp = _client.post(f'/tools/{name}', json={'arguments': arguments})
    resp.raise_for_status()
    return resp.json()


def get_resource(name: str) -> str:
    resp = _client.get(f'/resources/{name}')
    resp.raise_for_status()
    return resp.json()['content']


def get_prompt(name: str) -> str:
    safe = name.replace('/', '-')
    resp = _client.get(f'/prompts/{safe}')
    resp.raise_for_status()
    return resp.json()['content']


def health() -> bool:
    try:
        resp = _client.get('/health', timeout=3.0)
        return resp.status_code == 200
    except Exception:
        return False
