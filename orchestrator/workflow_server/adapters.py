"""Bisset v2 Test Runner Adapters — parse test runner output."""
import json
import re
from dataclasses import dataclass, field

_ANSI_RE = re.compile(r'\x1b\[[0-9;]*[A-Za-z]')


def strip_ansi(text: str) -> str:
    """Remove ANSI escape sequences (colors, cursor moves) from text."""
    return _ANSI_RE.sub('', text)


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
        output = strip_ansi(stdout + stderr)
        if exit_code == 0:
            return AdapterResult(passed=1, failed=0, raw_output=output)
        return AdapterResult(
            passed=0, failed=1,
            errors=[strip_ansi(stderr or stdout)],
            raw_output=output,
        )


class PytestAdapter:
    """Parse pytest output for pass/fail counts.

    Counts are matched independently because pytest prints failures first
    ("2 failed, 3 passed in 1.23s").
    """

    _PASSED_RE = re.compile(r'(\d+)\s+passed')
    _FAILED_RE = re.compile(r'(\d+)\s+failed')

    def parse(self, exit_code: int, stdout: str, stderr: str) -> AdapterResult:
        output = strip_ansi(stdout + stderr)
        m_passed = self._PASSED_RE.search(output)
        m_failed = self._FAILED_RE.search(output)
        if m_passed or m_failed:
            passed = int(m_passed.group(1)) if m_passed else 0
            failed = int(m_failed.group(1)) if m_failed else 0
            errors = [output] if failed > 0 else []
            return AdapterResult(
                passed=passed, failed=failed, errors=errors, raw_output=output,
            )
        # Fallback to exit code
        if exit_code == 0:
            return AdapterResult(passed=1, failed=0, raw_output=output)
        return AdapterResult(passed=0, failed=1, errors=[output], raw_output=output)


class BehaveAdapter:
    """Parse behave --format json output.

    behave does not emit pure JSON on stdout: the array is wrapped by a
    "USING RUNNER: ..." banner and a plain-text summary. The JSON array is
    extracted between the first '[' and the last ']'.

    Coverage is scenario coverage: passed scenarios / total scenarios * 100.
    """

    def parse(self, exit_code: int, stdout: str, stderr: str) -> AdapterResult:
        output = strip_ansi(stdout + stderr)
        try:
            start = stdout.index('[')
            end = stdout.rindex(']')
            data = json.loads(stdout[start:end + 1])
            passed = 0
            failed = 0
            errors: list[str] = []
            for feature in data:
                for element in feature.get("elements", []):
                    if element.get("type") != "scenario":
                        continue
                    status = element.get("status")
                    if status is None:
                        # Older behave: derive from step results
                        steps = element.get("steps", [])
                        ok = all(s.get("result", {}).get("status") == "passed"
                                 for s in steps)
                        status = "passed" if ok else "failed"
                    if status == "passed":
                        passed += 1
                    else:
                        failed += 1
                        errors.append(self._scenario_error(element))
            total = passed + failed
            coverage = round(passed / total * 100, 1) if total else 0.0
            return AdapterResult(passed=passed, failed=failed,
                                 coverage=coverage, errors=errors,
                                 raw_output=output)
        except (ValueError, KeyError, TypeError):
            # Fallback: no parsable JSON in output
            if exit_code == 0:
                return AdapterResult(passed=1, failed=0, raw_output=output)
            return AdapterResult(passed=0, failed=1, errors=[output],
                                 raw_output=output)

    @staticmethod
    def _scenario_error(element: dict) -> str:
        name = element.get("name", "<unnamed>")
        for step in element.get("steps", []):
            result = step.get("result", {})
            if result.get("status") not in (None, "passed"):
                msg = strip_ansi(result.get("error_message") or "no error message")
                return (f"Scenario '{name}' failed at step "
                        f"'{step.get('name', '?')}': {msg}")
        return f"Scenario '{name}' failed (step not reached or undefined)"


def get_adapter(name: str):
    """Factory function to get adapter by name."""
    adapters = {
        "pytest": PytestAdapter,
        "behave": BehaveAdapter,
        "generic": GenericAdapter,
    }
    return adapters.get(name, GenericAdapter)()
