"""
Tests for Workflow Engine (Task A3: Model-Aware Routing)
"""

import pytest
from unittest.mock import Mock, patch
from orchestrator.workflow_server.engine import (
    WorkflowEngine, ComplexityAnalyzer, ModelType, TaskMetrics
)


class TestComplexityAnalyzer:
    """Test complexity analysis and model recommendation."""

    def test_haiku_recommendation_simple_task(self):
        """Simple tasks should recommend Haiku."""
        metrics = ComplexityAnalyzer.analyze(
            title="Fix typo in README",
            description="There is a simple typo in the documentation"
        )
        assert metrics.recommended_model == ModelType.HAIKU
        assert metrics.complexity_score < 10

    def test_sonnet_recommendation_feature_task(self):
        """Feature implementation should recommend Sonnet."""
        metrics = ComplexityAnalyzer.analyze(
            title="Implement user authentication",
            description="Add JWT-based authentication with login/logout endpoints and validation logic"
        )
        assert metrics.recommended_model == ModelType.SONNET
        assert metrics.complexity_score >= 5

    def test_opus_recommendation_complex_task(self):
        """Complex architecture tasks should recommend Opus."""
        metrics = ComplexityAnalyzer.analyze(
            title="Design distributed microservices architecture",
            description="Create scalable, secure, concurrent system with performance optimization"
        )
        assert metrics.recommended_model == ModelType.OPUS
        assert metrics.complexity_score >= 20

    def test_score_calculation(self):
        """Score should increase with complexity indicators."""
        simple = ComplexityAnalyzer.analyze("Fix", "simple")
        complex_task = ComplexityAnalyzer.analyze(
            "Implement security",
            "performance optimization with concurrent distributed system"
        )
        assert complex_task.complexity_score > simple.complexity_score

    def test_metrics_dataclass(self):
        """TaskMetrics should store all fields."""
        metrics = TaskMetrics(
            title="Test",
            description="Test description",
            assigned_model=ModelType.SONNET,
            complexity_score=15.0,
            recommended_model=ModelType.SONNET
        )
        assert metrics.title == "Test"
        assert metrics.assigned_model == ModelType.SONNET
        assert metrics.recommended_model == ModelType.SONNET


class TestWorkflowEngine:
    """Test workflow engine with model routing."""

    @pytest.fixture
    def mock_db(self):
        """Create mock storage."""
        db = Mock()
        db.get_next_pending_task.return_value = {
            "id": "task-1",
            "title": "Implement feature",
            "description": "Complex feature requiring logic",
            "status": "pending"
        }
        db.get_task.return_value = {"id": "task-1"}
        db.update_task_model.return_value = True
        db.create_background_job.return_value = "job-1"
        db.get_background_job.return_value = {
            "id": "job-1",
            "status": "running"
        }
        db.update_background_job.return_value = True
        db.update_task_status.return_value = True
        db.add_event.return_value = True
        return db

    @pytest.fixture
    def engine(self, mock_db):
        """Create engine with mock DB."""
        return WorkflowEngine(mock_db)

    def test_get_next_task_with_recommendation(self, engine, mock_db):
        """Next task should include model recommendation."""
        task = engine.get_next_task("session-1")
        
        assert task is not None
        assert "recommended_model" in task
        assert "complexity_score" in task
        assert task["recommended_model"] in [m.value for m in ModelType]

    def test_assign_model(self, engine, mock_db):
        """Should assign model to task."""
        result = engine.assign_model("task-1", ModelType.SONNET.value)
        
        assert result is True
        mock_db.update_task_model.assert_called_once_with("task-1", ModelType.SONNET.value)

    def test_assign_model_invalid(self, engine):
        """Should reject invalid model names."""
        result = engine.assign_model("task-1", "invalid-model")
        assert result is False

    def test_recommend_model(self, engine):
        """Should return string model name."""
        model = engine.recommend_model(
            "Implement feature",
            "Complex logic implementation"
        )
        assert model in [m.value for m in ModelType]

    def test_background_job_lifecycle(self, engine, mock_db):
        """Should create and track background jobs."""
        # Create job
        job_id = engine.start_background_job("session-1", "bisset-interview")
        assert job_id == "job-1"
        mock_db.create_background_job.assert_called_once()

        # Get status
        status = engine.get_job_status("job-1")
        assert status is not None
        assert status["status"] == "running"

        # Update status
        result = engine.update_job_status("job-1", "completed", {"result": "ok"})
        assert result is True
        mock_db.update_background_job.assert_called_once()

    def test_list_jobs(self, engine, mock_db):
        """Should list jobs for session."""
        mock_db.list_background_jobs.return_value = [
            {"id": "job-1", "status": "completed"},
            {"id": "job-2", "status": "running"}
        ]
        
        jobs = engine.list_jobs("session-1")
        assert len(jobs) == 2

    def test_mark_task_complete(self, engine, mock_db):
        """Should mark task complete with test results."""
        result = engine.mark_task_complete(
            "task-1",
            {"passed": 10, "failed": 0}
        )
        
        assert result is True
        mock_db.update_task_status.assert_called_with("task-1", "completed")
        mock_db.add_event.assert_called_once()

    def test_fail_task(self, engine, mock_db):
        """Should mark task as failed."""
        result = engine.fail_task("task-1", "Test suite failed", retry_count=2)
        
        assert result is True
        mock_db.update_task_status.assert_called_with("task-1", "failed")
        mock_db.add_event.assert_called_once()

    def test_get_next_task_none(self, engine, mock_db):
        """Should return None if no pending tasks."""
        mock_db.get_next_pending_task.return_value = None
        
        task = engine.get_next_task("session-1")
        assert task is None
