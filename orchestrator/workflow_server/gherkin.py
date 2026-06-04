"""Gherkin helpers — feature filename handling and structural syntax check.

check_syntax() is a lightweight structural validation used by
step_set_feature to refuse writing obvious garbage to disk. Full grammar
and step-definition validation is step_validate_feature's job (behave
--dry-run).
"""
import re

_SLUG_RE = re.compile(r'[^a-z0-9]+')
_STEP_KEYWORDS = ("Given ", "When ", "Then ", "And ", "But ", "* ")
_SCENARIO_KEYWORDS = ("Scenario:", "Scenario Outline:")


def derive_filename(title: str) -> str:
    """Derive a safe .feature filename from a step title."""
    slug = _SLUG_RE.sub('-', title.lower()).strip('-') or "feature"
    return f"{slug}.feature"


def sanitize_filename(filename: str) -> str:
    """Reject path traversal and force the .feature extension."""
    name = filename.strip()
    if (not name or '/' in name or '\\' in name
            or name.startswith('.') or '..' in name):
        raise ValueError(f"Invalid feature filename: {filename!r}")
    if not name.endswith(".feature"):
        name += ".feature"
    return name


def check_syntax(content: str) -> list[str]:
    """Structural validation. Returns a list of errors (empty = ok)."""
    errors: list[str] = []
    lines = [ln.strip() for ln in content.splitlines()]
    meaningful = [ln for ln in lines if ln and not ln.startswith('#')]

    if not any(ln.startswith("Feature:") for ln in meaningful):
        errors.append("Missing 'Feature:' header")

    scenarios: list[tuple[str, int]] = []  # (name, step_count)
    current: str | None = None
    steps = 0
    for ln in meaningful:
        if ln.startswith(_SCENARIO_KEYWORDS):
            if current is not None:
                scenarios.append((current, steps))
            current = ln.split(":", 1)[1].strip() or "<unnamed>"
            steps = 0
        elif current is not None and ln.startswith(_STEP_KEYWORDS):
            steps += 1
    if current is not None:
        scenarios.append((current, steps))

    if not scenarios:
        errors.append("No 'Scenario:' found")
    for name, count in scenarios:
        if count == 0:
            errors.append(f"Scenario '{name}' has no steps")
    return errors
