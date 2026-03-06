"""
Tests for Prompt Registry and Caching (Task A5)
"""

import pytest
from orchestrator.mcp_server.prompts import PromptRegistry, PromptDefinition


class TestPromptRegistry:
    """Test prompt registration and retrieval."""

    def test_get_all_prompts(self):
        """Should have 7 phase prompts registered."""
        prompts = PromptRegistry.get_all_prompts()
        
        assert len(prompts) == 7
        assert "phase_2_interview" in prompts
        assert "phase_2_5_validation" in prompts
        assert "phase_3_architect" in prompts
        assert "phase_4_gherkin" in prompts
        assert "phase_5_implement" in prompts
        assert "phase_6_coverage" in prompts
        assert "phase_7_review" in prompts

    def test_get_specific_prompt(self):
        """Should retrieve prompt by phase name."""
        prompt = PromptRegistry.get_prompt("phase_2_interview")
        
        assert prompt is not None
        assert isinstance(prompt, PromptDefinition)
        assert prompt.phase == "phase_2_interview"
        assert "interview" in prompt.name.lower()
        assert len(prompt.content) > 100

    def test_get_nonexistent_prompt(self):
        """Should return None for nonexistent prompt."""
        prompt = PromptRegistry.get_prompt("nonexistent")
        
        assert prompt is None

    def test_prompt_definition_fields(self):
        """PromptDefinition should have required fields."""
        prompt = PromptRegistry.get_prompt("phase_2_interview")
        
        assert hasattr(prompt, 'phase')
        assert hasattr(prompt, 'name')
        assert hasattr(prompt, 'content')
        assert hasattr(prompt, 'can_cache')
        assert hasattr(prompt, 'min_cache_tokens')

    def test_all_prompts_have_content(self):
        """All prompts should have non-empty content."""
        prompts = PromptRegistry.get_all_prompts()
        
        for phase, prompt in prompts.items():
            assert len(prompt.content) > 100, f"Prompt {phase} has insufficient content"
            assert prompt.name, f"Prompt {phase} missing name"


class TestPromptCaching:
    """Test caching logic for large specs."""

    def test_small_spec_no_cache(self):
        """Spec < 10K chars should not cache."""
        small_spec = "This is a small specification" * 10  # ~300 chars
        
        assert not PromptRegistry.should_cache(small_spec)

    def test_large_spec_cache(self):
        """Spec > 10K chars should cache."""
        large_spec = "This is a specification. " * 500  # ~12,500 chars
        
        assert PromptRegistry.should_cache(large_spec)

    def test_boundary_spec_10k(self):
        """Spec exactly 10K should not cache (boundary)."""
        boundary_spec = "a" * 10000
        
        assert not PromptRegistry.should_cache(boundary_spec)

    def test_boundary_spec_10k_plus_1(self):
        """Spec 10K+1 should cache."""
        boundary_spec = "a" * 10001
        
        assert PromptRegistry.should_cache(boundary_spec)

    def test_cache_headers_small_spec(self):
        """Small spec should have no cache headers."""
        small_spec = "small" * 100
        headers = PromptRegistry.get_cache_headers(small_spec)
        
        assert headers == {}

    def test_cache_headers_large_spec(self):
        """Large spec should have ephemeral cache header."""
        large_spec = "large specification content. " * 400  # ~11,200 chars
        headers = PromptRegistry.get_cache_headers(large_spec)
        
        assert "cache-control" in headers
        assert headers["cache-control"] == "ephemeral"


class TestPromptContent:
    """Test prompt content quality."""

    def test_interview_prompt_has_interview_guidance(self):
        """Interview prompt should have question-asking guidance."""
        prompt = PromptRegistry.get_prompt("phase_2_interview")
        
        assert "question" in prompt.content.lower()
        assert "interview" in prompt.content.lower()

    def test_validation_prompt_has_scoring(self):
        """Validation prompt should have scoring criteria."""
        prompt = PromptRegistry.get_prompt("phase_2_5_validation")
        
        assert "score" in prompt.content.lower()
        assert "completeness" in prompt.content.lower()

    def test_architect_prompt_has_paradigms(self):
        """Architecture prompt should mention paradigms."""
        prompt = PromptRegistry.get_prompt("phase_3_architect")
        
        assert "oop" in prompt.content.lower() or "object-oriented" in prompt.content.lower()
        assert "functional" in prompt.content.lower()
        assert "data-oriented" in prompt.content.lower()

    def test_gherkin_prompt_has_feature_syntax(self):
        """Gherkin prompt should have Given-When-Then."""
        prompt = PromptRegistry.get_prompt("phase_4_gherkin")
        
        assert "given" in prompt.content.lower()
        assert "when" in prompt.content.lower()
        assert "then" in prompt.content.lower()

    def test_coverage_prompt_has_threshold(self):
        """Coverage prompt should mention 80% threshold."""
        prompt = PromptRegistry.get_prompt("phase_6_coverage")
        
        assert "80" in prompt.content

    def test_all_prompts_have_signal_instructions(self):
        """Prompts should have signal/completion instructions."""
        prompts = PromptRegistry.get_all_prompts()
        
        signal_keywords = ["signal", "complete", "done", "next"]
        for phase, prompt in prompts.items():
            content_lower = prompt.content.lower()
            has_signal = any(kw in content_lower for kw in signal_keywords)
            assert has_signal, f"Prompt {phase} missing signal/completion instruction"


class TestPromptCoverage:
    """Verify all workflow phases have prompts."""

    def test_all_phases_covered(self):
        """All workflow phases should have prompts."""
        phases = [
            "phase_2_interview",
            "phase_2_5_validation",
            "phase_3_architect",
            "phase_4_gherkin",
            "phase_5_implement",
            "phase_6_coverage",
            "phase_7_review",
        ]
        
        for phase in phases:
            prompt = PromptRegistry.get_prompt(phase)
            assert prompt is not None, f"Missing prompt for {phase}"
            assert prompt.can_cache is True

    def test_prompt_names_descriptive(self):
        """Prompt names should describe their phase."""
        prompts = PromptRegistry.get_all_prompts()
        
        for phase, prompt in prompts.items():
            assert len(prompt.name) > 5
            assert "phase" not in prompt.name.lower() or "phase" in phase
