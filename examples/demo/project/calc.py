"""Tiny calculator — the demo target implementation.

This file ships with a deliberate bug: subtract() has its operands
swapped. The BDD gate demo shows Bisset blocking step acceptance until
the bug is fixed (see examples/demo/fix/calc.py).
"""


def add(a, b):
    return a + b


def subtract(a, b):
    return b - a  # BUG: operands swapped, spec requires a - b
