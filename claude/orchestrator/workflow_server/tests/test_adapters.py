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


def test_get_adapter_factory():
    assert isinstance(get_adapter("pytest"), PytestAdapter)
    assert isinstance(get_adapter("behave"), BehaveAdapter)
    assert isinstance(get_adapter("generic"), GenericAdapter)
    assert isinstance(get_adapter("unknown"), GenericAdapter)
