"""Tests for Bisset v2 Prompt Template System."""
import pytest
from orchestrator.mcp_server.prompts import PromptTemplate, PromptRegistry


def test_template_render_with_vars():
    tpl = PromptTemplate("test", "Hello {{name}}, project is {{project.name}}.")
    result = tpl.render(
        db_vars={"project.name": "MyApp"},
        context_vars={"name": "Claude"}
    )
    assert result == "Hello Claude, project is MyApp."


def test_missing_context_var_replacement():
    tpl = PromptTemplate("test", "Step: {{step.title}}, Dir: {{context.directory_structure}}")
    result = tpl.render(
        db_vars={"step.title": "Build API"},
        context_vars={}
    )
    assert "Build API" in result
    assert "[not provided: context.directory_structure]" in result


def test_registry_get_prompt():
    registry = PromptRegistry()
    prompt = registry.get_prompt("bisset/implementer")
    assert prompt is not None
    assert isinstance(prompt, PromptTemplate)
    assert "bisset/implementer" == prompt.name


def test_registry_list_prompts():
    registry = PromptRegistry()
    names = registry.list_prompts()
    assert "bisset/interviewer" in names
    assert "bisset/architect" in names
    assert "bisset/analyzer" in names
    assert "bisset/implementer" in names
    assert "bisset/test-writer" in names


def test_registry_render_prompt():
    registry = PromptRegistry()
    result = registry.render(
        "bisset/implementer",
        db_vars={"step.title": "Build API", "project.name": "MyApp"},
        context_vars={"context.relevant_files": "src/api.py"}
    )
    assert isinstance(result, str)
    assert len(result) > 0
    # Should not contain unresolved DB vars that were provided
    assert "{{step.title}}" not in result


def test_interviewer_prompt_mentions_interview_tools():
    reg = PromptRegistry()
    text = reg.render("bisset/interviewer", {}, {})
    for tool in ("interview_question", "interview_answer", "interview_complete"):
        assert tool in text


def test_analyzer_prompt_mentions_analysis_tools():
    reg = PromptRegistry()
    text = reg.render("bisset/analyzer", {}, {})
    for tool in ("analysis_submit", "analysis_view",
                 "analysis_approve", "analysis_discard"):
        assert tool in text
    # the prompt must forbid bypassing the proposal with manual step_add
    assert "step_add" in text
