"""
Security validation utilities.
Prevents path traversal attacks and dangerous shell commands.
"""
import os
import re
import shlex

# Commands never allowed regardless of context
_BLOCKED_COMMANDS = frozenset({
    'rm', 'rmdir', 'shred', 'dd', 'mkfs', 'fdisk',
    'chmod', 'chown', 'sudo', 'su', 'passwd',
    'nc', 'ncat', 'netcat', 'curl', 'wget', 'bash', 'sh', 'zsh', 'fish',
    'python', 'python3', 'node', 'ruby', 'perl',  # only allowed via test_runner meta
    'eval', 'exec', 'source',
})

# Shell metacharacters that indicate injection attempts
_SHELL_METACHARS = re.compile(r'[;&|`$><!()\[\]{}*?\\]')


class SecurityError(ValueError):
    """Raised when a security validation fails."""


def validate_path(base: str, candidate: str) -> str:
    """
    Resolve ``candidate`` relative to ``base`` and ensure it stays inside ``base``.
    Returns the resolved absolute path.
    Raises SecurityError on traversal.
    """
    if not base:
        raise SecurityError('base path must be set')
    base_real = os.path.realpath(os.path.abspath(base))
    cand_real = os.path.realpath(os.path.abspath(os.path.join(base, candidate)
                                                  if not os.path.isabs(candidate)
                                                  else candidate))
    if not cand_real.startswith(base_real + os.sep) and cand_real != base_real:
        raise SecurityError(
            f'Path traversal detected: {candidate!r} resolves outside {base!r}'
        )
    return cand_real


def validate_features_path(project_path: str, features_dir: str) -> str:
    """Validate that features_dir is inside project_path."""
    return validate_path(project_path, features_dir)


def validate_command(cmd: list[str]) -> list[str]:
    """
    Validate a command list (as passed to subprocess.run).
    Raises SecurityError if any element contains shell metacharacters or the
    executable is in the blocked list.
    Returns the cmd unchanged if safe.
    """
    if not cmd:
        raise SecurityError('Empty command')
    executable = os.path.basename(cmd[0])
    if executable in _BLOCKED_COMMANDS:
        raise SecurityError(
            f'Command {executable!r} is not allowed as a test runner. '
            'Set test_runner to your BDD test executable (e.g. behave, pytest, cargo, cucumber).'
        )
    for part in cmd:
        if _SHELL_METACHARS.search(part):
            raise SecurityError(
                f'Shell metacharacter detected in command argument: {part!r}. '
                'Pass arguments via test_runner_args without shell expansion.'
            )
    return cmd


def safe_split_args(args_str: str) -> list[str]:
    """Split a space-separated args string safely using shlex (no shell expansion)."""
    if not args_str:
        return []
    try:
        return shlex.split(args_str)
    except ValueError as e:
        raise SecurityError(f'Cannot parse test_runner_args: {e}') from e
