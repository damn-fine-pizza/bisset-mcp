"""Tests for Bisset v2 MCP client URL mapping."""
import pytest
from orchestrator.mcp_server.client import _GET_TOOLS, _build_url


def test_get_tools_set():
    """All read-only tools must be in _GET_TOOLS."""
    expected_gets = {
        "project_detect", "project_list",
        "session_status", "session_list",
        "step_current", "step_list",
        "pipeline_view", "pipeline_report",
        "event_log",
    }
    assert expected_gets.issubset(_GET_TOOLS)


def test_post_tools_not_in_get():
    """Write tools must NOT be in _GET_TOOLS."""
    post_tools = {
        "project_create", "project_switch",
        "session_start", "session_resume",
        "step_run_tests", "step_complete", "step_skip",
        "step_add", "step_remove", "step_edit", "step_reorder",
        "pipeline_set_rules",
    }
    assert post_tools.isdisjoint(_GET_TOOLS)


def test_build_url_simple():
    """Simple tool names map to /{tool_name}."""
    url, remaining = _build_url("project_create", {"name": "myapp", "path": "/tmp"})
    assert url == "/project_create"
    assert remaining == {"name": "myapp", "path": "/tmp"}


def test_build_url_with_query_params():
    """GET tools pass all args as remaining (query params)."""
    url, remaining = _build_url("session_status", {"session_id": "abc123"})
    assert url == "/session_status"
    assert remaining == {"session_id": "abc123"}
