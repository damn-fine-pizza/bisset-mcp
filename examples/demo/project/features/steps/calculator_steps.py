"""Step definitions binding calculator.feature to calc.py."""
import sys
from pathlib import Path

from behave import given, when, then

# Make the project root (where calc.py lives) importable
sys.path.insert(0, str(Path(__file__).resolve().parents[2]))

import calc  # noqa: E402


@given("the numbers {a:d} and {b:d}")
def step_given_numbers(ctx, a, b):
    ctx.a, ctx.b = a, b


@when("I add them")
def step_when_add(ctx):
    ctx.result = calc.add(ctx.a, ctx.b)


@when("I subtract them")
def step_when_subtract(ctx):
    ctx.result = calc.subtract(ctx.a, ctx.b)


@then("the result is {expected:d}")
def step_then_result(ctx, expected):
    assert ctx.result == expected, f"expected {expected}, got {ctx.result}"
