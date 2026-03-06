"""Bisset v2 Test Runner Adapters — parse test runner output."""
import json
import re
from dataclasses import dataclass, field


@dataclass
class AdapterResult:
    """Structured result from a test runner execution."""
    passed: int = 0
    failed: int = 0
    coverage: float = 0.0
    errors: list[str] = field(default_factory=list)
    raw_output: str = ""

    @property
    def total(self) -> int:
        return self.passed + self.failed

    @property
    def all_passed(self) -> bool:
        return self.failed == 0 and self.passed >= 0


class GenericAdapter:
    """Generic adapter — exit code 0 = pass, else fail. No coverage."""

    def parse(self, exit_code: int, stdout: str, stderr: str) -> AdapterResult:
        if exit_code == 0:
            return AdapterResult(passed=1, failed=0, raw_output=stdout)
        return AdapterResult(
            passed=0, failed=1,
            errors=[stderr or stdout],
            raw_output=stdout + stderr,
        )


class PytestAdapter:
    """Parse pytest output for pass/fail counts."""

    _RESULT_RE = re.compile(
        r'(\d+)\s+passed(?:.*?(\d+)\s+failed)?'
    )

    def parse(self, exit_code: int, stdout: str, stderr: str) -> AdapterResult:
        output = stdout + stderr
        m = self._RESULT_RE.search(output)
        if m:
            passed = int(m.group(1))
            failed = int(m.group(2)) if m.group(2) else 0
            return AdapterResult(
                passed=passed, failed=failed, raw_output=output,
            )
        # Fallback to exit code
        if exit_code == 0:
            return AdapterResult(passed=1, failed=0, raw_output=output)
        return AdapterResult(passed=0, failed=1, errors=[output], raw_output=output)


class BehaveAdapter:
    """Parse behave --format json output."""

    def parse(self, exit_code: int, stdout: str, stderr: str) -> AdapterResult:
        output = stdout + stderr
        try:
            data = json.loads(stdout)
            passed = 0
            failed = 0
            for feature in data:
                for element in feature.get("elements", []):
                    steps = element.get("steps", [])
                    if all(s.get("result", {}).get("status") == "passed" for s in steps):
                        passed += 1
                    else:
                        failed += 1
            return AdapterResult(passed=passed, failed=failed, raw_output=output)
        except (json.JSONDecodeError, KeyError, TypeError):
            # Fallback
            if exit_code == 0:
                return AdapterResult(passed=1, failed=0, raw_output=output)
            return AdapterResult(passed=0, failed=1, errors=[output], raw_output=output)


def get_adapter(name: str):
    """Factory function to get adapter by name."""
    adapters = {
        "pytest": PytestAdapter,
        "behave": BehaveAdapter,
        "generic": GenericAdapter,
    }
    return adapters.get(name, GenericAdapter)()
