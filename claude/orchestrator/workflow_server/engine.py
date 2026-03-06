"""
Workflow Engine - Task Management & Model-Aware Routing

This module handles:
- Task lifecycle management
- Model recommendation based on complexity
- Sub-agent dispatching
- Workflow state transitions
- Session orchestration

Completely independent implementation for Claude MCP.
"""

import json
from dataclasses import dataclass
from enum import Enum
from typing import Optional, Dict, List, Any
from .storage import Storage


class ModelType(str, Enum):
    """Available Claude models."""
    HAIKU = "claude-3-5-haiku"
    SONNET = "claude-3-5-sonnet"
    OPUS = "claude-3-opus"


@dataclass
class TaskMetrics:
    """Metrics for determining model assignment."""
    title: str
    description: str
    assigned_model: Optional[ModelType] = None
    complexity_score: float = 0.0
    recommended_model: Optional[ModelType] = None


class ComplexityAnalyzer:
    """Analyzes task descriptions to determine complexity and model recommendation."""

    # Keywords for complexity scoring
    HAIKU_KEYWORDS = {
        "simple", "basic", "trivial", "straightforward", "quick", "minor",
        "small", "fix", "patch", "typo", "comment", "format"
    }

    SONNET_KEYWORDS = {
        "implement", "feature", "module", "component", "service", "logic",
        "algorithm", "refactor", "middleware", "endpoint", "validation",
        "transform", "parse", "generate", "complex", "moderate"
    }

    OPUS_KEYWORDS = {
        "architect", "design", "optimize", "performance", "security",
        "distributed", "async", "concurrent", "parallel", "machine learning",
        "cryptography", "compliance", "integration", "migration", "critical",
        "expert", "advanced", "sophisticated", "complex system", "research"
    }

    COMPLEXITY_WEIGHTS = {
        "dependencies": 2.0,
        "tests": 1.5,
        "integration": 2.0,
        "migration": 3.0,
        "performance": 2.5,
        "security": 2.5,
        "documentation": 0.5,
    }

    @staticmethod
    def analyze(title: str, description: str) -> TaskMetrics:
        """
        Analyze task and return recommended model and complexity score.
        
        Args:
            title: Task title
            description: Task description
        
        Returns:
            TaskMetrics with complexity_score and recommended_model
        """
        combined = f"{title} {description}".lower()
        score = 0.0

        # Count keyword matches with weighting
        for keyword, weight in ComplexityAnalyzer.COMPLEXITY_WEIGHTS.items():
            if keyword in combined:
                score += weight

        # Analyze specific keywords
        opus_count = sum(1 for kw in ComplexityAnalyzer.OPUS_KEYWORDS if kw in combined)
        sonnet_count = sum(1 for kw in ComplexityAnalyzer.SONNET_KEYWORDS if kw in combined)
        haiku_count = sum(1 for kw in ComplexityAnalyzer.HAIKU_KEYWORDS if kw in combined)

        # Normalize scores with better calibration
        score += opus_count * 5.0
        score += sonnet_count * 2.5
        score += haiku_count * 0.5

        # Determine recommended model based on score
        if score >= 15:
            recommended = ModelType.OPUS
        elif score >= 5:
            recommended = ModelType.SONNET
        else:
            recommended = ModelType.HAIKU

        metrics = TaskMetrics(
            title=title,
            description=description,
            complexity_score=score,
            recommended_model=recommended
        )
        return metrics


class WorkflowEngine:
    """
    Main workflow orchestration engine.
    
    Manages task routing, model assignment, and workflow state transitions.
    """

    def __init__(self, db: Storage):
        """Initialize engine with storage backend."""
        self.db = db
        self.analyzer = ComplexityAnalyzer()

    def get_next_task(self, session_id: str) -> Optional[Dict[str, Any]]:
        """
        Get next pending task for session.
        
        Args:
            session_id: Session UUID
        
        Returns:
            Task dict with recommended_model, or None if no pending tasks
        """
        task = self.db.get_next_pending_task(session_id)
        if not task:
            return None

        # Analyze for model recommendation
        metrics = self.analyzer.analyze(task["title"], task["description"])
        task["recommended_model"] = metrics.recommended_model.value
        task["complexity_score"] = metrics.complexity_score

        return task

    def assign_model(
        self,
        task_id: str,
        model: str,
        override: bool = False
    ) -> bool:
        """
        Assign or override model for task.
        
        Args:
            task_id: Task UUID
            model: Model name (haiku/sonnet/opus)
            override: Force override if already assigned
        
        Returns:
            True if assignment successful
        """
        try:
            # Validate model
            if model not in [m.value for m in ModelType]:
                return False

            # Check if already assigned
            task = self.db.get_task(task_id)
            if task and task.get("assigned_model") and not override:
                return False

            # Store assignment
            self.db.update_task_model(task_id, model)
            return True
        except Exception:
            return False

    def recommend_model(self, title: str, description: str) -> str:
        """
        Get model recommendation for a title/description pair.
        
        Args:
            title: Task title
            description: Task description
        
        Returns:
            Recommended model name
        """
        metrics = self.analyzer.analyze(title, description)
        return metrics.recommended_model.value

    def start_background_job(
        self,
        session_id: str,
        agent_name: str,
        task_id: Optional[str] = None
    ) -> str:
        """
        Create a background job for async execution.
        
        Args:
            session_id: Session UUID
            agent_name: Name of agent (e.g., "bisset-interview")
            task_id: Optional associated task
        
        Returns:
            Job ID
        """
        job_id = self.db.create_background_job(
            session_id=session_id,
            agent_name=agent_name,
            task_id=task_id
        )
        return job_id

    def get_job_status(self, job_id: str) -> Optional[Dict[str, Any]]:
        """
        Get current job status.
        
        Args:
            job_id: Job UUID
        
        Returns:
            Job dict with status and result, or None if not found
        """
        return self.db.get_background_job(job_id)

    def update_job_status(
        self,
        job_id: str,
        status: str,
        result: Optional[Dict[str, Any]] = None
    ) -> bool:
        """
        Update job status and optional result.
        
        Args:
            job_id: Job UUID
            status: New status (running/completed/failed)
            result: Optional result dict
        
        Returns:
            True if updated successfully
        """
        return self.db.update_background_job(
            job_id=job_id,
            status=status,
            result=result
        )

    def list_jobs(self, session_id: str, status: Optional[str] = None) -> List[Dict[str, Any]]:
        """
        List background jobs for a session.
        
        Args:
            session_id: Session UUID
            status: Optional filter by status
        
        Returns:
            List of job dicts
        """
        return self.db.list_background_jobs(session_id, status)

    def mark_task_complete(
        self,
        task_id: str,
        test_results: Dict[str, Any]
    ) -> bool:
        """
        Mark task as complete with test results.
        
        Args:
            task_id: Task UUID
            test_results: Test execution results
        
        Returns:
            True if marked successfully
        """
        try:
            self.db.update_task_status(task_id, "completed")
            self.db.add_event(
                session_id=None,
                event_type="task_completed",
                data={
                    "task_id": task_id,
                    "test_results": test_results
                }
            )
            return True
        except Exception:
            return False

    def fail_task(
        self,
        task_id: str,
        error: str,
        retry_count: int = 0
    ) -> bool:
        """
        Mark task as failed.
        
        Args:
            task_id: Task UUID
            error: Error message
            retry_count: Number of retries
        
        Returns:
            True if marked successfully
        """
        try:
            self.db.update_task_status(task_id, "failed")
            self.db.add_event(
                session_id=None,
                event_type="task_failed",
                data={
                    "task_id": task_id,
                    "error": error,
                    "retry_count": retry_count
                }
            )
            return True
        except Exception:
            return False
