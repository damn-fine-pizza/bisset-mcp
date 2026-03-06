"""
FastAPI Application Server - Workflow HTTP Endpoints for Claude MCP

Provides HTTP API for Bisset workflow orchestration with Claude SDK compatibility.
All responses wrapped in Claude SDK `TextContent` format with metadata.

Completely independent implementation for Claude - no shared code with copilot/.
"""

import time
import json
from typing import Optional, Dict, Any, List
from contextlib import asynccontextmanager

try:
    from fastapi import FastAPI, HTTPException, Request
    from fastapi.responses import JSONResponse
except ImportError:
    raise ImportError("FastAPI required: pip install fastapi uvicorn")

from .storage import Storage
from .engine import WorkflowEngine


class ResponseWrapper:
    """Wraps responses in Claude SDK compatible TextContent format with metadata."""

    @staticmethod
    def success(data: Any, duration_ms: float = 0.0) -> Dict[str, Any]:
        """
        Wrap successful response in Claude SDK format.
        
        Args:
            data: Response payload (dict or string)
            duration_ms: Operation duration in milliseconds
        
        Returns:
            Dict with TextContent format compatible with Claude SDK
        """
        text_content = json.dumps(data) if not isinstance(data, str) else data
        return {
            "content": [
                {
                    "type": "text",
                    "text": text_content
                }
            ],
            "is_error": False,
            "metadata": {
                "success": True,
                "duration_ms": duration_ms
            }
        }

    @staticmethod
    def error(message: str, code: str = "ERROR", status: int = 400) -> Dict[str, Any]:
        """
        Wrap error response in Claude SDK format.
        
        Args:
            message: Human-readable error message
            code: Error code (e.g., NOT_FOUND, INVALID_MODEL)
            status: HTTP status code
        
        Returns:
            Dict with error in TextContent format
        """
        return {
            "content": [
                {
                    "type": "text",
                    "text": json.dumps({
                        "error": message,
                        "code": code
                    })
                }
            ],
            "is_error": True,
            "metadata": {
                "success": False,
                "error_code": code,
                "status": status
            }
        }


@asynccontextmanager
async def lifespan(app: FastAPI):
    """Application lifecycle management."""
    # Startup
    app.state.db = Storage()
    app.state.engine = WorkflowEngine(app.state.db)
    yield
    # Shutdown
    if hasattr(app.state, 'db'):
        app.state.db.close()


app = FastAPI(
    title="Claude Bisset Workflow Server",
    description="MCP workflow orchestration for Claude - BDD-first development",
    version="1.0.0",
    lifespan=lifespan
)


@app.middleware("http")
async def response_timing_middleware(request: Request, call_next):
    """Track response timing for all endpoints."""
    start = time.time()
    response = await call_next(request)
    duration_ms = (time.time() - start) * 1000
    response.headers["X-Response-Time-Ms"] = str(duration_ms)
    return response


# ============================================================================
# Session Management
# ============================================================================

@app.post("/workflow_new_session")
async def create_session(
    project_name: Optional[str] = None,
    mcp_client: Optional[str] = None,
) -> Dict[str, Any]:
    """
    Create new workflow session.
    
    Request:
    {
      "project_name": "my-app",
      "mcp_client": "claude-mcp"
    }
    
    Response:
    {
      "content": [{"type": "text", "text": "{\\"id\\": \\"session-123\\", ...}"}],
      "is_error": false,
      "metadata": {"duration_ms": 45}
    }
    """
    start = time.time()
    try:
        session = app.state.db.create_session(
            project_name=project_name,
            mcp_client=mcp_client or "claude-mcp"
        )
        duration = (time.time() - start) * 1000
        return ResponseWrapper.success(session, duration)
    except Exception as e:
        return ResponseWrapper.error(str(e), "SESSION_CREATE_ERROR", 500)


@app.get("/workflow_detect_session")
async def detect_session() -> Dict[str, Any]:
    """
    Detect or retrieve current session.
    
    Response:
    {
      "content": [{"type": "text", "text": "{\\"id\\": \\"session-123\\"}"}],
      "is_error": false,
      "metadata": {"duration_ms": 12}
    }
    """
    start = time.time()
    try:
        # In Claude MCP context, get most recent session
        sessions = app.state.db.get_sessions()
        if sessions:
            session = sessions[-1]  # Most recent
        else:
            # Create new if none exists
            session = app.state.db.create_session(mcp_client="claude-mcp")
        
        duration = (time.time() - start) * 1000
        return ResponseWrapper.success(session, duration)
    except Exception as e:
        return ResponseWrapper.error(str(e), "SESSION_DETECT_ERROR", 500)


@app.get("/workflow_get_session/{session_id}")
async def get_session(session_id: str) -> Dict[str, Any]:
    """
    Get session details.
    
    Response:
    {
      "content": [{"type": "text", "text": "{\\"id\\": \\"session-123\\", \\"status\\": \\"interview\\"}"}],
      "is_error": false,
      "metadata": {"duration_ms": 8}
    }
    """
    start = time.time()
    try:
        session = app.state.db.get_session(session_id)
        if not session:
            return ResponseWrapper.error("Session not found", "NOT_FOUND", 404)
        
        duration = (time.time() - start) * 1000
        return ResponseWrapper.success(session, duration)
    except Exception as e:
        return ResponseWrapper.error(str(e), "SESSION_GET_ERROR", 500)


# ============================================================================
# Interview & Questions
# ============================================================================

@app.post("/workflow_start_interview/{session_id}")
async def start_interview(session_id: str) -> Dict[str, Any]:
    """
    Initialize interview phase - get first question.
    
    Response:
    {
      "content": [{"type": "text", "text": "{\\"question_id\\": \\"q-1\\", \\"text\\": \\"What is...\\"}"}],
      "is_error": false,
      "metadata": {"duration_ms": 25}
    }
    """
    start = time.time()
    try:
        question = app.state.db.get_next_question(session_id)
        if not question:
            result = {"signal": "interview_complete", "message": "No questions available"}
        else:
            result = question
        
        duration = (time.time() - start) * 1000
        return ResponseWrapper.success(result, duration)
    except Exception as e:
        return ResponseWrapper.error(str(e), "INTERVIEW_START_ERROR", 500)


@app.get("/workflow_next_question/{session_id}")
async def get_next_question(session_id: str) -> Dict[str, Any]:
    """
    Get next unanswered question for session.
    
    Response:
    {
      "content": [{"type": "text", "text": "{\\"id\\": \\"q-2\\", \\"text\\": \\"What are...\\"}"}],
      "is_error": false,
      "metadata": {"duration_ms": 10}
    }
    """
    start = time.time()
    try:
        question = app.state.db.get_next_question(session_id)
        if not question:
            result = {"signal": "interview_complete"}
        else:
            result = question
        
        duration = (time.time() - start) * 1000
        return ResponseWrapper.success(result, duration)
    except Exception as e:
        return ResponseWrapper.error(str(e), "QUESTION_GET_ERROR", 500)


@app.post("/workflow_record_answer/{session_id}/{question_id}")
async def record_answer(
    session_id: str,
    question_id: str,
    answer: str
) -> Dict[str, Any]:
    """
    Record answer to a question.
    
    Request:
    {
      "answer": "The system should handle user authentication via OAuth2"
    }
    
    Response:
    {
      "content": [{"type": "text", "text": "{\\"status\\": \\"recorded\\"}"}],
      "is_error": false,
      "metadata": {"duration_ms": 15}
    }
    """
    start = time.time()
    try:
        app.state.db.record_answer(question_id, answer)
        result = {"question_id": question_id, "status": "recorded"}
        
        duration = (time.time() - start) * 1000
        return ResponseWrapper.success(result, duration)
    except Exception as e:
        return ResponseWrapper.error(str(e), "ANSWER_RECORD_ERROR", 500)


@app.get("/workflow_list_questions/{session_id}")
async def list_questions(session_id: str) -> Dict[str, Any]:
    """
    List all questions with answer status.
    
    Response:
    {
      "content": [{"type": "text", "text": "[{\\"id\\": \\"q-1\\", \\"answered\\": true}, ...]"}],
      "is_error": false,
      "metadata": {"duration_ms": 20}
    }
    """
    start = time.time()
    try:
        questions = app.state.db.get_questions(session_id)
        duration = (time.time() - start) * 1000
        return ResponseWrapper.success({"questions": questions}, duration)
    except Exception as e:
        return ResponseWrapper.error(str(e), "QUESTIONS_LIST_ERROR", 500)


# ============================================================================
# Spec Management
# ============================================================================

@app.post("/workflow_freeze_spec/{session_id}")
async def freeze_spec(session_id: str) -> Dict[str, Any]:
    """
    Freeze specification (mark as ready for architecture phase).
    
    Response:
    {
      "content": [{"type": "text", "text": "{\\"signal\\": \\"spec_frozen\\"}"}],
      "is_error": false,
      "metadata": {"duration_ms": 8}
    }
    """
    start = time.time()
    try:
        app.state.db.freeze_spec(session_id)
        result = {"signal": "spec_frozen"}
        
        duration = (time.time() - start) * 1000
        return ResponseWrapper.success(result, duration)
    except Exception as e:
        return ResponseWrapper.error(str(e), "SPEC_FREEZE_ERROR", 500)


@app.get("/workflow_get_spec/{session_id}")
async def get_spec(session_id: str) -> Dict[str, Any]:
    """
    Get current specification.
    
    Response:
    {
      "content": [{"type": "text", "text": "{\\"spec\\": \\"...\\""}],
      "is_error": false,
      "metadata": {"duration_ms": 10}
    }
    """
    start = time.time()
    try:
        session = app.state.db.get_session(session_id)
        if not session or not session.get("spec"):
            return ResponseWrapper.error("Spec not found", "NOT_FOUND", 404)
        
        result = {
            "spec": session["spec"],
            "frozen_at": session.get("spec_frozen_at")
        }
        
        duration = (time.time() - start) * 1000
        return ResponseWrapper.success(result, duration)
    except Exception as e:
        return ResponseWrapper.error(str(e), "SPEC_GET_ERROR", 500)


# ============================================================================
# Task Management
# ============================================================================

@app.get("/workflow_next_task/{session_id}")
async def get_next_task(session_id: str) -> Dict[str, Any]:
    """
    Get next pending task with model recommendation.
    
    Response:
    {
      "content": [{"type": "text", "text": "{\\"id\\": \\"task-1\\", \\"recommended_model\\": \\"sonnet\\"}"}],
      "is_error": false,
      "metadata": {"duration_ms": 12}
    }
    """
    start = time.time()
    try:
        task = app.state.engine.get_next_task(session_id)
        if not task:
            result = {"signal": "all_tasks_complete"}
        else:
            result = task
        
        duration = (time.time() - start) * 1000
        return ResponseWrapper.success(result, duration)
    except Exception as e:
        return ResponseWrapper.error(str(e), "TASK_GET_ERROR", 500)


@app.post("/workflow_assign_model/{session_id}/{task_id}")
async def assign_model(
    session_id: str,
    task_id: str,
    model: str
) -> Dict[str, Any]:
    """
    Assign specific model to task (override recommendation).
    
    Request:
    {
      "model": "opus"
    }
    
    Response:
    {
      "content": [{"type": "text", "text": "{\\"assigned_model\\": \\"opus\\"}"}],
      "is_error": false,
      "metadata": {"duration_ms": 8}
    }
    """
    start = time.time()
    try:
        success = app.state.engine.assign_model(task_id, model)
        if not success:
            return ResponseWrapper.error("Invalid model or task", "INVALID_MODEL", 400)
        
        result = {"task_id": task_id, "assigned_model": model}
        
        duration = (time.time() - start) * 1000
        return ResponseWrapper.success(result, duration)
    except Exception as e:
        return ResponseWrapper.error(str(e), "MODEL_ASSIGN_ERROR", 500)


@app.post("/workflow_accept_task_result/{session_id}/{task_id}")
async def complete_task(
    session_id: str,
    task_id: str,
    test_results: Optional[Dict[str, Any]] = None
) -> Dict[str, Any]:
    """
    Mark task as complete with test results.
    
    Request:
    {
      "test_results": {"passed": 15, "failed": 0}
    }
    
    Response:
    {
      "content": [{"type": "text", "text": "{\\"status\\": \\"completed\\"}"}],
      "is_error": false,
      "metadata": {"duration_ms": 10}
    }
    """
    start = time.time()
    try:
        success = app.state.engine.mark_task_complete(task_id, test_results or {})
        if not success:
            return ResponseWrapper.error("Failed to complete task", "COMPLETION_ERROR", 500)
        
        result = {"task_id": task_id, "status": "completed"}
        
        duration = (time.time() - start) * 1000
        return ResponseWrapper.success(result, duration)
    except Exception as e:
        return ResponseWrapper.error(str(e), "TASK_COMPLETE_ERROR", 500)


# ============================================================================
# Background Jobs & Async Mode
# ============================================================================

@app.post("/workflow_start_agent/{session_id}")
async def start_background_job(
    session_id: str,
    agent_name: str,
    task_id: Optional[str] = None
) -> Dict[str, Any]:
    """
    Start background job for async agent execution.
    
    Request:
    {
      "agent_name": "bisset-interview",
      "task_id": null
    }
    
    Response:
    {
      "content": [{"type": "text", "text": "{\\"job_id\\": \\"job-123\\", \\"status\\": \\"created\\"}"}],
      "is_error": false,
      "metadata": {"duration_ms": 5}
    }
    """
    start = time.time()
    try:
        job_id = app.state.engine.start_background_job(
            session_id=session_id,
            agent_name=agent_name,
            task_id=task_id
        )
        result = {"job_id": job_id, "status": "created"}
        
        duration = (time.time() - start) * 1000
        return ResponseWrapper.success(result, duration)
    except Exception as e:
        return ResponseWrapper.error(str(e), "JOB_CREATE_ERROR", 500)


@app.get("/workflow_get_job_status/{session_id}/{job_id}")
async def get_job_status(session_id: str, job_id: str) -> Dict[str, Any]:
    """
    Get background job status and result (if complete).
    
    Response:
    {
      "content": [{"type": "text", "text": "{\\"status\\": \\"running\\"}"}],
      "is_error": false,
      "metadata": {"duration_ms": 6}
    }
    """
    start = time.time()
    try:
        job = app.state.engine.get_job_status(job_id)
        if not job:
            return ResponseWrapper.error("Job not found", "NOT_FOUND", 404)
        
        duration = (time.time() - start) * 1000
        return ResponseWrapper.success(job, duration)
    except Exception as e:
        return ResponseWrapper.error(str(e), "JOB_GET_ERROR", 500)


@app.get("/workflow_list_jobs/{session_id}")
async def list_jobs(
    session_id: str,
    status: Optional[str] = None
) -> Dict[str, Any]:
    """
    List background jobs for session.
    
    Response:
    {
      "content": [{"type": "text", "text": "{\\"jobs\\": [...]}"}],
      "is_error": false,
      "metadata": {"duration_ms": 15}
    }
    """
    start = time.time()
    try:
        jobs = app.state.engine.list_jobs(session_id, status)
        
        duration = (time.time() - start) * 1000
        return ResponseWrapper.success({"jobs": jobs}, duration)
    except Exception as e:
        return ResponseWrapper.error(str(e), "JOB_LIST_ERROR", 500)


# ============================================================================
# Status & Introspection
# ============================================================================

@app.get("/workflow_status/{session_id}")
async def get_status(session_id: str) -> Dict[str, Any]:
    """
    Get overall workflow status.
    
    Response:
    {
      "content": [{"type": "text", "text": "{\\"phase\\": \\"architecture\\"}"}],
      "is_error": false,
      "metadata": {"duration_ms": 10}
    }
    """
    start = time.time()
    try:
        session = app.state.db.get_session(session_id)
        if not session:
            return ResponseWrapper.error("Session not found", "NOT_FOUND", 404)
        
        result = {
            "session_id": session_id,
            "phase": session.get("phase", "interview"),
            "status": "active"
        }
        
        duration = (time.time() - start) * 1000
        return ResponseWrapper.success(result, duration)
    except Exception as e:
        return ResponseWrapper.error(str(e), "STATUS_GET_ERROR", 500)


@app.get("/workflow_get_events/{session_id}")
async def get_events(session_id: str, limit: int = 100) -> Dict[str, Any]:
    """
    Get event log for session.
    
    Response:
    {
      "content": [{"type": "text", "text": "{\\"events\\": [...]}"}],
      "is_error": false,
      "metadata": {"duration_ms": 20}
    }
    """
    start = time.time()
    try:
        events = app.state.db.list_events(session_id, limit)
        
        duration = (time.time() - start) * 1000
        return ResponseWrapper.success({"events": events}, duration)
    except Exception as e:
        return ResponseWrapper.error(str(e), "EVENTS_GET_ERROR", 500)


# ============================================================================
# Health & Info
# ============================================================================

@app.get("/health")
async def health_check() -> Dict[str, Any]:
    """
    Health check endpoint.
    
    Response:
    {
      "status": "healthy",
      "version": "1.0.0"
    }
    """
    return {
        "status": "healthy",
        "version": "1.0.0",
        "service": "claude-bisset-workflow"
    }


@app.get("/info")
async def server_info() -> Dict[str, Any]:
    """
    Server information and capabilities.
    
    Response:
    {
      "name": "Claude Bisset Workflow Server",
      "features": [...]
    }
    """
    return {
        "name": "Claude Bisset Workflow Server",
        "version": "1.0.0",
        "mcp_protocol": "stdio",
        "features": [
            "workflow_sessions",
            "interview_questions",
            "spec_management",
            "task_routing",
            "model_aware_assignment",
            "background_jobs",
            "prompt_caching",
            "async_mode"
        ]
    }


if __name__ == "__main__":
    import uvicorn
    uvicorn.run(app, host="127.0.0.1", port=8765)
