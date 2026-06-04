"""Tests for Bisset v2 Test Runner Adapters."""
import pytest
from orchestrator.workflow_server.adapters import (
    AdapterResult, GenericAdapter, PytestAdapter, BehaveAdapter, get_adapter
)


def test_adapter_result_properties():
    r = AdapterResult(passed=5, failed=2)
    assert r.total == 7
    assert r.all_passed is False
    r2 = AdapterResult(passed=5, failed=0)
    assert r2.all_passed is True


def test_generic_adapter_pass():
    adapter = GenericAdapter()
    result = adapter.parse(exit_code=0, stdout="OK", stderr="")
    assert result.all_passed is True
    assert result.passed == 1
    assert result.failed == 0


def test_generic_adapter_fail():
    adapter = GenericAdapter()
    result = adapter.parse(exit_code=1, stdout="FAIL", stderr="error")
    assert result.all_passed is False
    assert result.failed == 1


def test_pytest_adapter_parse():
    adapter = PytestAdapter()
    stdout = "===== 5 passed, 2 failed in 1.23s ====="
    result = adapter.parse(exit_code=1, stdout=stdout, stderr="")
    assert result.passed == 5
    assert result.failed == 2
    assert result.total == 7


def test_pytest_adapter_failed_first_order():
    """Real pytest prints failures first: '2 failed, 3 passed in 1.23s'."""
    adapter = PytestAdapter()
    stdout = "===== 2 failed, 3 passed in 1.23s ====="
    result = adapter.parse(exit_code=1, stdout=stdout, stderr="")
    assert result.passed == 3
    assert result.failed == 2


def test_pytest_adapter_strips_ansi():
    adapter = PytestAdapter()
    stdout = "\x1b[31mERROR collecting tests\x1b[0m\nModuleNotFoundError: no module"
    result = adapter.parse(exit_code=2, stdout=stdout, stderr="")
    assert result.failed == 1
    assert all("\x1b" not in e for e in result.errors)


_BEHAVE_REALISTIC = """USING RUNNER: behave.runner:Runner
[
{"keyword": "Feature", "name": "Calculator", "status": "failed", "elements": [
  {"type": "scenario", "name": "Add two numbers", "status": "passed",
   "steps": [{"name": "ok", "result": {"status": "passed"}}]},
  {"type": "scenario", "name": "Subtract two numbers", "status": "failed",
   "steps": [{"name": "the result is 1", "result": {"status": "failed", "error_message": "ASSERT FAILED: -1 != 1"}}]}
]}
]

Failing scenarios:
  features/calc.feature:7  Subtract two numbers

0 features passed, 1 failed, 0 skipped
1 scenario passed, 1 failed, 0 skipped
"""


def test_behave_adapter_realistic_output():
    """behave --format json wraps the JSON with a runner banner and a text summary."""
    adapter = BehaveAdapter()
    result = adapter.parse(exit_code=1, stdout=_BEHAVE_REALISTIC, stderr="")
    assert result.passed == 1
    assert result.failed == 1
    assert result.coverage == 50.0
    assert any("Subtract two numbers" in e for e in result.errors)


def test_behave_adapter_all_pass_full_coverage():
    adapter = BehaveAdapter()
    stdout = """USING RUNNER: behave.runner:Runner
[
{"keyword": "Feature", "name": "Calc", "status": "passed", "elements": [
  {"type": "scenario", "name": "Add", "status": "passed", "steps": []},
  {"type": "scenario", "name": "Sub", "status": "passed", "steps": []}
]}
]
2 scenarios passed, 0 failed, 0 skipped
"""
    result = adapter.parse(exit_code=0, stdout=stdout, stderr="")
    assert result.passed == 2
    assert result.failed == 0
    assert result.coverage == 100.0


def test_get_adapter_factory():
    assert isinstance(get_adapter("pytest"), PytestAdapter)
    assert isinstance(get_adapter("behave"), BehaveAdapter)
    assert isinstance(get_adapter("generic"), GenericAdapter)
    assert isinstance(get_adapter("unknown"), GenericAdapter)
