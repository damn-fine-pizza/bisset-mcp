"""HTTP client for Bisset v2 MCP -- communicates with workflow_server backend.

Tool names map directly to workflow_server endpoint paths.
GET tools (reads) use GET with query params; everything else uses POST with JSON body.
"""
import os
import logging
import httpx

BACKEND_URL = os.environ.get("WORKFLOW_BACKEND_URL", "http://127.0.0.1:8765")

logger = logging.getLogger("bisset-mcp-client")

# Tools that use GET (read-only)
_GET_TOOLS = {
    "project_detect",
    "project_list",
    "session_status",
    "session_list",
    "step_current",
    "step_list",
    "pipeline_view",
    "pipeline_report",
    "event_log",
    "step_get_feature",
    "step_validate_feature",
}


def _build_url(tool_name: str, arguments: dict) -> tuple[str, dict]:
    """Return (url, remaining_args). All v2 endpoints use flat /{tool_name}."""
    return f"/{tool_name}", dict(arguments)


def call_tool(name: str, arguments: dict) -> dict:
    """Forward MCP tool call to the workflow_server and return its response."""
    logger.info("-> tool=%s", name)
    url, params = _build_url(name, arguments or {})

    with httpx.Client(base_url=BACKEND_URL, timeout=30.0) as client:
        if name in _GET_TOOLS:
            resp = client.get(url, params=params)
        else:
            resp = client.post(url, json=params)
        resp.raise_for_status()

    result = resp.json()
    logger.info("<- tool=%s status=%s", name, resp.status_code)
    return result


def health() -> bool:
    """Return True if the workflow_server is up and healthy."""
    try:
        with httpx.Client(base_url=BACKEND_URL, timeout=3.0) as client:
            return client.get("/health").status_code == 200
    except Exception:
        return False
