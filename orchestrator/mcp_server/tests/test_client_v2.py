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


def test_gherkin_tools_routing():
    from orchestrator.mcp_server.client import _GET_TOOLS
    # reads go through GET, the write goes through POST
    assert "step_get_feature" in _GET_TOOLS
    assert "step_validate_feature" in _GET_TOOLS
    assert "step_set_feature" not in _GET_TOOLS


def test_gherkin_tools_exposed():
    from orchestrator.mcp_server.server import BissetMCPServer
    tools = {t["name"] for t in BissetMCPServer()._build_tools()}
    assert {"step_set_feature", "step_get_feature", "step_validate_feature"} <= tools


def test_interview_tools_exposed():
    from orchestrator.mcp_server.server import BissetMCPServer
    tools = {t["name"] for t in BissetMCPServer()._build_tools()}
    assert {"interview_question", "interview_answer", "interview_complete"} <= tools


def test_interview_tools_routing():
    from orchestrator.mcp_server.client import _GET_TOOLS
    # all three are writes: they must go through POST
    assert "interview_question" not in _GET_TOOLS
    assert "interview_answer" not in _GET_TOOLS
    assert "interview_complete" not in _GET_TOOLS


def test_analysis_tools_exposed():
    from orchestrator.mcp_server.server import BissetMCPServer
    tools = {t["name"] for t in BissetMCPServer()._build_tools()}
    assert {"analysis_submit", "analysis_view",
            "analysis_approve", "analysis_discard"} <= tools


def test_analysis_tools_routing():
    from orchestrator.mcp_server.client import _GET_TOOLS
    # the read goes through GET, the writes through POST
    assert "analysis_view" in _GET_TOOLS
    assert "analysis_submit" not in _GET_TOOLS
    assert "analysis_approve" not in _GET_TOOLS
    assert "analysis_discard" not in _GET_TOOLS
