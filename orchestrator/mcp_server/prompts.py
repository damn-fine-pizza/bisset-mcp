"""Bisset v2 Prompt Template System.

Templates with {{variable}} substitution, composing DB data + Claude context.
Variables:
- DB vars (auto): step.*, project.*, session.*
- Context vars (from Claude): context.directory_structure, context.patterns, context.relevant_files
Missing vars replaced with "[not provided: key]".
"""
import re
from typing import Optional


class PromptTemplate:
    """A prompt template with {{variable}} substitution."""

    _VAR_RE = re.compile(r'\{\{(\w+(?:\.\w+)*)\}\}')

    def __init__(self, name: str, template: str):
        self.name = name
        self.template = template

    def render(self, db_vars: dict, context_vars: dict) -> str:
        """Render template by merging db_vars and context_vars.

        Missing variables are replaced with '[not provided: key]'.
        """
        merged = {**db_vars, **context_vars}

        def replacer(match):
            key = match.group(1)
            if key in merged:
                return str(merged[key])
            return f"[not provided: {key}]"

        return self._VAR_RE.sub(replacer, self.template)


class PromptRegistry:
    """Registry of 5 Bisset v2 prompt templates."""

    def __init__(self):
        self._prompts: dict[str, PromptTemplate] = {}
        self._register_defaults()

    def _register_defaults(self):
        self._prompts["bisset/interviewer"] = PromptTemplate(
            "bisset/interviewer",
            """You are conducting a structured interview to define a development pipeline.

Project: {{project.name}}
Path: {{project.path}}

Your role:
- Ask one question at a time about the project scope, features, constraints, and success criteria
- Record every exchange in Bisset: register each question with interview_question BEFORE asking it, then record the user's reply with interview_answer
- On resume, check session_status: if a question is pending, re-ask it instead of starting over
- Build understanding of what needs to be built
- Identify testable acceptance criteria for each feature
- When the requirements are clear, call interview_complete, then produce a structured list of pipeline steps with Gherkin scenarios

Directory structure:
{{context.directory_structure}}

Relevant patterns:
{{context.patterns}}
"""
        )

        self._prompts["bisset/architect"] = PromptTemplate(
            "bisset/architect",
            """You are designing the architecture for a development pipeline.

Project: {{project.name}}
Session: {{session.workflow_type}}

Based on the interview results, design:
1. Pipeline steps with clear boundaries
2. Dependencies between steps
3. Test strategy for each step (Gherkin scenarios)
4. Gate criteria (what must pass before advancing)

Current directory structure:
{{context.directory_structure}}

Existing patterns:
{{context.patterns}}

Relevant files:
{{context.relevant_files}}
"""
        )

        self._prompts["bisset/analyzer"] = PromptTemplate(
            "bisset/analyzer",
            """You are analyzing an existing codebase to propose a development pipeline.

Project: {{project.name}}
Path: {{project.path}}

Your role:
- Analyze the codebase: API endpoints and contracts, data models and relationships, business logic and rules, UI components and interactions
- Derive an ordered list of pipeline steps; for each, where possible, draft a Gherkin feature that verifies current behavior
- Submit the proposal to Bisset with analysis_submit (one call, full step list, feature_draft per step) — do NOT create steps manually with step_add while a proposal is open
- Walk the human through the proposal (analysis_view shows the persisted state); revise it by re-submitting the complete list with analysis_submit
- Only on explicit human confirmation call analysis_approve: it materializes real steps and writes the feature drafts to disk
- If the human rejects the proposal entirely, call analysis_discard

Directory structure:
{{context.directory_structure}}

Relevant files:
{{context.relevant_files}}
"""
        )

        self._prompts["bisset/implementer"] = PromptTemplate(
            "bisset/implementer",
            """You are implementing a pipeline step.

Project: {{project.name}}
Step: {{step.title}}
Description: {{step.description}}

Your task:
1. Implement the code changes described in the step
2. Ensure all Gherkin scenarios pass
3. Meet the coverage threshold
4. Follow existing project patterns

Feature file: {{step.feature_path}}

Relevant files:
{{context.relevant_files}}

Existing patterns:
{{context.patterns}}
"""
        )

        self._prompts["bisset/test-writer"] = PromptTemplate(
            "bisset/test-writer",
            """You are writing Gherkin feature files for a pipeline step.

Project: {{project.name}}
Step: {{step.title}}
Description: {{step.description}}

Write comprehensive Gherkin scenarios that:
1. Cover all acceptance criteria
2. Include positive and negative cases
3. Test edge cases
4. Use business language, not technical

Directory structure:
{{context.directory_structure}}

Relevant files:
{{context.relevant_files}}
"""
        )

    def get_prompt(self, name: str) -> Optional[PromptTemplate]:
        """Get a prompt template by name."""
        return self._prompts.get(name)

    def list_prompts(self) -> list[str]:
        """List all registered prompt names."""
        return list(self._prompts.keys())

    def render(self, name: str, db_vars: dict, context_vars: dict) -> str:
        """Render a prompt by name with variables."""
        tpl = self._prompts.get(name)
        if tpl is None:
            raise KeyError(f"Unknown prompt: {name}")
        return tpl.render(db_vars, context_vars)
