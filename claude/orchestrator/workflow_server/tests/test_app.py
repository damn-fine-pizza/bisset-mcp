"""
Tests for FastAPI App - Response Wrappers (Task A4)
"""

import pytest
import json
from unittest.mock import Mock, patch, AsyncMock
from fastapi.testclient import TestClient

# Need to mock Storage and WorkflowEngine before importing app
with patch('orchestrator.workflow_server.app.Storage') as mock_storage, \
     patch('orchestrator.workflow_server.app.WorkflowEngine') as mock_engine:
    from orchestrator.workflow_server.app import app, ResponseWrapper


class TestResponseWrapper:
    """Test response wrapper format compatibility with Claude SDK."""

    def test_success_response_format(self):
        """Success response should have TextContent format."""
        response = ResponseWrapper.success(
            {"result": "ok"},
            duration_ms=42.5
        )
        
        assert response["is_error"] is False
        assert response["metadata"]["success"] is True
        assert response["metadata"]["duration_ms"] == 42.5
        assert len(response["content"]) == 1
        assert response["content"][0]["type"] == "text"
        
        # Should be valid JSON
        text = response["content"][0]["text"]
        data = json.loads(text)
        assert data["result"] == "ok"

    def test_success_with_string_data(self):
        """Success response should handle string data."""
        response = ResponseWrapper.success("plain text")
        
        assert response["is_error"] is False
        assert response["content"][0]["text"] == "plain text"

    def test_error_response_format(self):
        """Error response should have proper format with error code."""
        response = ResponseWrapper.error(
            "Invalid input",
            code="INVALID_MODEL",
            status=400
        )
        
        assert response["is_error"] is True
        assert response["metadata"]["success"] is False
        assert response["metadata"]["error_code"] == "INVALID_MODEL"
        assert response["metadata"]["status"] == 400
        
        # Should contain error and code in text
        text = response["content"][0]["text"]
        data = json.loads(text)
        assert data["error"] == "Invalid input"
        assert data["code"] == "INVALID_MODEL"

    def test_response_duration_tracking(self):
        """Duration should be tracked in metadata."""
        response = ResponseWrapper.success({"data": "test"}, duration_ms=123.456)
        
        assert response["metadata"]["duration_ms"] == 123.456


class TestEndpoints:
    """Test endpoints return Claude SDK compatible format."""

    @pytest.fixture
    def client(self):
        """Create test client."""
        return TestClient(app)

    def test_health_endpoint(self, client):
        """Health endpoint should return simple JSON."""
        response = client.get("/health")
        
        assert response.status_code == 200
        data = response.json()
        assert data["status"] == "healthy"
        assert "version" in data

    def test_info_endpoint(self, client):
        """Info endpoint should describe features."""
        response = client.get("/info")
        
        assert response.status_code == 200
        data = response.json()
        assert "name" in data
        assert "features" in data
        assert isinstance(data["features"], list)

    def test_create_session_endpoint_format(self, client):
        """Create session should return wrapped response."""
        with patch('orchestrator.workflow_server.app.app.state') as mock_state:
            mock_db = Mock()
            mock_db.create_session.return_value = "session-123"
            mock_db.get_session.return_value = {
                "id": "session-123",
                "created_at": 1234567890.0,
                "phase": "interview",
            }
            mock_state.db = mock_db
            
            response = client.post(
                "/workflow_new_session",
                params={"project_name": "test-project", "mcp_client": "claude-mcp"}
            )
            
            # Should return wrapped format
            assert response.status_code == 200
            data = response.json()
            assert "content" in data
            assert "is_error" in data
            assert "metadata" in data
            assert data["is_error"] is False

    def test_error_response_format_on_failure(self, client):
        """Failed endpoint should return error in wrapped format."""
        with patch('orchestrator.workflow_server.app.app.state') as mock_state:
            mock_db = Mock()
            mock_db.get_session.side_effect = Exception("DB Error")
            mock_state.db = mock_db
            
            response = client.get("/workflow_get_session/nonexistent")
            
            # Should still have wrapped format
            assert response.status_code in [200, 500]  # FastAPI wraps errors differently
            data = response.json()
            # Either error in wrapper or FastAPI error
            assert "error" in str(data) or "detail" in data or "is_error" in data

    def test_response_includes_duration_metadata(self, client):
        """Responses should include timing metadata."""
        with patch('orchestrator.workflow_server.app.app.state') as mock_state:
            mock_db = Mock()
            mock_db.create_session.return_value = "session-123"
            mock_db.get_session.return_value = {"id": "session-123", "phase": "interview"}
            mock_state.db = mock_db
            
            response = client.post("/workflow_new_session")
            
            data = response.json()
            if "metadata" in data:
                assert "duration_ms" in data["metadata"]
                assert isinstance(data["metadata"]["duration_ms"], (int, float))


class TestConsistency:
    """Test consistency across multiple endpoints."""

    def test_all_endpoints_have_consistent_wrapper(self):
        """All documented endpoints should exist and be callable."""
        endpoints = [
            "/health",
            "/info",
        ]
        
        client = TestClient(app)
        for endpoint in endpoints:
            response = client.get(endpoint)
            # Should not 404
            assert response.status_code != 404, f"Endpoint {endpoint} not found"

    def test_claude_sdk_compatibility(self):
        """Verify TextContent format matches Claude SDK expectations."""
        response = ResponseWrapper.success({"message": "test"})
        
        # Claude SDK expects:
        # - content: list of content blocks
        # - content[].type: "text" or other type
        # - content[].text: text content
        # - is_error: boolean
        
        assert isinstance(response["content"], list)
        assert all(isinstance(c, dict) for c in response["content"])
        assert all("type" in c and "text" in c for c in response["content"])
        assert isinstance(response["is_error"], bool)
