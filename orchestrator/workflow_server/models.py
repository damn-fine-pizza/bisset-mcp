from dataclasses import dataclass
from typing import Optional, Dict, Any

@dataclass
class SessionMeta:
    id: str
    name: Optional[str] = None
    project_meta: Dict[str, Any] = None

@dataclass
class Task:
    id: str
    title: str
    description: Optional[str] = ''
    acceptance_criteria: Optional[str] = ''
    status: str = 'pending'

@dataclass
class TestRun:
    id: str
    task_id: str
    passed: int = 0
    failed: int = 0
    coverage_pct: float = 0.0

# This module provides simple in-memory data structures for reference and tests.
