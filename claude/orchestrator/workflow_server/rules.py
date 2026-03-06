"""Bisset v2 Rule Engine — declarative when/then DSL."""
from enum import Enum


class Action(str, Enum):
    ADVANCE = "advance"
    RETRY = "retry"
    ASK_USER = "ask_user"
    ABORT = "abort"
    SKIP = "skip"


ALLOWED_VARS = {
    "tests_pass", "tests_fail", "coverage", "retries",
    "gate", "no_tests", "step.order", "always",
}


class RuleEngine:
    """Evaluate declarative when/then rules against a context."""

    def __init__(self, rules: list[dict]):
        self.rules = rules

    def evaluate(self, **context) -> Action:
        """Evaluate rules in order, return first matching action."""
        context["always"] = True
        for rule in self.rules:
            if self._eval_when(rule["when"], context):
                return Action(rule["then"])
        return Action.ABORT

    def _eval_when(self, expr: str, context: dict) -> bool:
        """Safe expression evaluator. NO eval() or exec().

        Hand-written tokenizer + recursive descent parser.
        Supports: AND, OR, NOT, ==, !=, >=, <=, >, <
        All identifiers validated against ALLOWED_VARS.
        Unknown variables raise ValueError.
        """
        tokens = self._tokenize(expr)
        result, pos = self._parse_or(tokens, 0, context)
        return result

    def _tokenize(self, expr: str) -> list[str]:
        """Tokenize expression into tokens."""
        tokens = []
        i = 0
        while i < len(expr):
            if expr[i].isspace():
                i += 1
            elif expr[i:i+2] in ('>=', '<=', '!=', '=='):
                tokens.append(expr[i:i+2])
                i += 2
            elif expr[i] in ('>', '<'):
                tokens.append(expr[i])
                i += 1
            elif expr[i] == "'":
                # String literal
                j = i + 1
                while j < len(expr) and expr[j] != "'":
                    j += 1
                tokens.append(expr[i:j+1])
                i = j + 1
            elif expr[i] == '"':
                j = i + 1
                while j < len(expr) and expr[j] != '"':
                    j += 1
                tokens.append(expr[i:j+1])
                i = j + 1
            elif expr[i].isdigit() or (expr[i] == '-' and i+1 < len(expr) and expr[i+1].isdigit()):
                j = i + 1
                while j < len(expr) and (expr[j].isdigit() or expr[j] == '.'):
                    j += 1
                tokens.append(expr[i:j])
                i = j
            elif expr[i].isalpha() or expr[i] == '_':
                j = i
                while j < len(expr) and (expr[j].isalnum() or expr[j] in ('_', '.')):
                    j += 1
                tokens.append(expr[i:j])
                i = j
            else:
                i += 1
        return tokens

    def _parse_or(self, tokens, pos, ctx):
        left, pos = self._parse_and(tokens, pos, ctx)
        while pos < len(tokens) and tokens[pos].upper() == 'OR':
            pos += 1
            right, pos = self._parse_and(tokens, pos, ctx)
            left = left or right
        return left, pos

    def _parse_and(self, tokens, pos, ctx):
        left, pos = self._parse_not(tokens, pos, ctx)
        while pos < len(tokens) and tokens[pos].upper() == 'AND':
            pos += 1
            right, pos = self._parse_not(tokens, pos, ctx)
            left = left and right
        return left, pos

    def _parse_not(self, tokens, pos, ctx):
        if pos < len(tokens) and tokens[pos].upper() == 'NOT':
            pos += 1
            val, pos = self._parse_comparison(tokens, pos, ctx)
            return not val, pos
        return self._parse_comparison(tokens, pos, ctx)

    def _parse_comparison(self, tokens, pos, ctx):
        left, pos = self._parse_value(tokens, pos, ctx)
        if pos < len(tokens) and tokens[pos] in ('==', '!=', '>=', '<=', '>', '<'):
            op = tokens[pos]
            pos += 1
            right, pos = self._parse_value(tokens, pos, ctx)
            if op == '==': return left == right, pos
            if op == '!=': return left != right, pos
            if op == '>=': return left >= right, pos
            if op == '<=': return left <= right, pos
            if op == '>': return left > right, pos
            if op == '<': return left < right, pos
        # Boolean context: truthy check
        return bool(left), pos

    def _parse_value(self, tokens, pos, ctx):
        if pos >= len(tokens):
            return False, pos
        tok = tokens[pos]
        # String literal
        if tok.startswith("'") or tok.startswith('"'):
            return tok[1:-1], pos + 1
        # Number
        try:
            if '.' in tok:
                return float(tok), pos + 1
            return int(tok), pos + 1
        except ValueError:
            pass
        # Variable lookup
        if tok not in ALLOWED_VARS:
            raise ValueError(f"Unknown variable in rule expression: '{tok}'")
        # Resolve dotted names
        if '.' in tok:
            parts = tok.split('.')
            val = ctx
            for p in parts:
                if isinstance(val, dict):
                    val = val.get(p)
                else:
                    val = getattr(val, p, None)
            return val, pos + 1
        return ctx.get(tok), pos + 1
