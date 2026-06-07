"""Tests for Gherkin helpers: filename derivation and structural syntax check."""
import pytest
from orchestrator.workflow_server.gherkin import (
    derive_filename, sanitize_filename, check_syntax
)


def test_derive_filename_slugifies_title():
    assert derive_filename("Implement calculator") == "implement-calculator.feature"
    assert derive_filename("  Càlc!! v2  ") == "c-lc-v2.feature"
    assert derive_filename("***") == "feature.feature"


def test_sanitize_filename_accepts_simple_names():
    assert sanitize_filename("calc.feature") == "calc.feature"
    assert sanitize_filename("calc") == "calc.feature"


@pytest.mark.parametrize("bad", [
    "../evil.feature", "a/b.feature", "a\\b.feature", ".hidden", "/abs.feature",
])
def test_sanitize_filename_rejects_traversal(bad):
    with pytest.raises(ValueError):
        sanitize_filename(bad)


VALID = """Feature: Calculator
  Scenario: Add
    Given the numbers 1 and 2
    When I add them
    Then the result is 3
"""


def test_check_syntax_valid():
    assert check_syntax(VALID) == []


def test_check_syntax_missing_feature_header():
    errors = check_syntax("Scenario: X\n  Given y\n")
    assert any("Feature:" in e for e in errors)


def test_check_syntax_no_scenarios():
    errors = check_syntax("Feature: X\n")
    assert any("Scenario" in e for e in errors)


def test_check_syntax_scenario_without_steps():
    content = "Feature: X\n  Scenario: empty\n  Scenario: ok\n    Given z\n"
    errors = check_syntax(content)
    assert any("empty" in e for e in errors)


@pytest.mark.parametrize("header", ["Scenario:", "Scenario Outline:"])
def test_check_syntax_accepts_scenario_variants(header):
    content = f"Feature: X\n  {header} Y\n    Given z\n"
    assert check_syntax(content) == []


def test_check_syntax_ignores_comments():
    content = "# preamble\nFeature: X\n  Scenario: S\n    # comment\n    Given z\n"
    assert check_syntax(content) == []
