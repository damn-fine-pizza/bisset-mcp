"""Tests for Bisset v2 Rule Engine."""
import pytest
from orchestrator.workflow_server.rules import RuleEngine, Action


DEFAULT_RULES = [
    {"when": "gate == 'human_approval'", "then": "ask_user"},
    {"when": "no_tests", "then": "ask_user"},
    {"when": "tests_pass AND coverage >= 80", "then": "advance"},
    {"when": "tests_fail AND retries < 3", "then": "retry"},
    {"when": "tests_fail AND retries >= 3", "then": "ask_user"},
    {"when": "always", "then": "abort"},
]


def test_advance_on_passing_tests():
    engine = RuleEngine(DEFAULT_RULES)
    result = engine.evaluate(tests_pass=True, tests_fail=False, coverage=85, retries=0,
                             gate="tests_only", no_tests=False)
    assert result == Action.ADVANCE


def test_retry_on_failing():
    engine = RuleEngine(DEFAULT_RULES)
    result = engine.evaluate(tests_pass=False, tests_fail=True, coverage=50, retries=1,
                             gate="tests_only", no_tests=False)
    assert result == Action.RETRY


def test_ask_user_after_max_retries():
    engine = RuleEngine(DEFAULT_RULES)
    result = engine.evaluate(tests_pass=False, tests_fail=True, coverage=50, retries=3,
                             gate="tests_only", no_tests=False)
    assert result == Action.ASK_USER


def test_ask_user_on_human_approval_gate():
    engine = RuleEngine(DEFAULT_RULES)
    result = engine.evaluate(tests_pass=True, tests_fail=False, coverage=90, retries=0,
                             gate="human_approval", no_tests=False)
    assert result == Action.ASK_USER


def test_ask_user_when_no_tests():
    engine = RuleEngine(DEFAULT_RULES)
    result = engine.evaluate(tests_pass=False, tests_fail=False, coverage=0, retries=0,
                             gate="tests_only", no_tests=True)
    assert result == Action.ASK_USER


def test_abort_fallback():
    # With only a fallback rule
    engine = RuleEngine([{"when": "always", "then": "abort"}])
    result = engine.evaluate(tests_pass=False, tests_fail=False, coverage=0, retries=0,
                             gate="tests_only", no_tests=False)
    assert result == Action.ABORT


def test_step_override_rules():
    override = [
        {"when": "tests_pass", "then": "advance"},
        {"when": "always", "then": "skip"},
    ]
    engine = RuleEngine(override)
    result = engine.evaluate(tests_pass=False, tests_fail=True, coverage=0, retries=0,
                             gate="tests_only", no_tests=False)
    assert result == Action.SKIP


def test_invalid_when_raises():
    engine = RuleEngine([{"when": "unknown_var", "then": "advance"}])
    with pytest.raises(ValueError):
        engine.evaluate(tests_pass=True)
