"""
FastAPI Application Server - Bisset v2 Workflow HTTP Endpoints

Provides HTTP API for Bisset v2 workflow orchestration with Claude SDK compatibility.
All responses wrapped in Claude SDK TextContent format with metadata.
Zero logic in endpoints -- everything forwarded to WorkflowEngine.
"""

import os
import time
import json
from typing import Any, Dict
from contextlib import asynccontextmanager

try:
    from fastapi import FastAPI, Request
except ImportError:
    raise ImportError("FastAPI required: pip install fastapi uvicorn")

from .storage import Storage
from .engine import WorkflowEngine


class ResponseWrapper:
    """Wraps responses in Claude SDK compatible TextContent format with metadata."""

    @staticmethod
    def success(data: Any, duration_ms: float = 0.0) -> Dict[str, Any]:
        """Wrap successful response in Claude SDK format."""
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
        """Wrap error response in Claude SDK format."""
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


# Module-level override for testing: set to ":memory:" before creating TestClient
_db_path_override: str | None = None


def _override_db_path(path: str | None) -> None:
    """Set a DB path override (use ':memory:' for tests). Pass None to reset."""
    global _db_path_override
    _db_path_override = path


@asynccontextmanager
async def lifespan(app: FastAPI):
    """Application lifecycle management."""
    # Priority: test override > DATABASE_PATH env > Storage default (~/.bisset/bisset.db)
    db_path = _db_path_override or os.environ.get("DATABASE_PATH") or None
    app.state.db = Storage(db_path=db_path)
    app.state.engine = WorkflowEngine(app.state.db)
    yield
    if hasattr(app.state, "db"):
        app.state.db.close()


app = FastAPI(
    title="Claude Bisset Workflow Server",
    description="MCP workflow orchestration for Claude - BDD-first development",
    version="2.0.0",
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
# Health
# ============================================================================

@app.get("/health")
async def health_check() -> Dict[str, Any]:
    """Health check endpoint."""
    return {
        "status": "healthy",
        "version": "2.0.0",
        "service": "claude-bisset-workflow"
    }


# ============================================================================
# Project
# ============================================================================

@app.post("/project_create")
async def project_create(request: Request) -> Dict[str, Any]:
    """Create a new project."""
    start = time.time()
    try:
        body = await request.json()
        name = body["name"]
        path = body["path"]
        config = {k: v for k, v in body.items() if k not in ("name", "path")}
        pid = request.app.state.engine.create_project(name, path, **config)
        duration = (time.time() - start) * 1000
        return ResponseWrapper.success({"project_id": pid}, duration)
    except Exception as e:
        return ResponseWrapper.error(str(e), "PROJECT_CREATE_ERROR", 500)


@app.get("/project_detect")
async def project_detect(request: Request, cwd: str) -> Dict[str, Any]:
    """Detect project by working directory path."""
    start = time.time()
    try:
        project = request.app.state.engine.detect_project(cwd)
        if not project:
            return ResponseWrapper.error("No project found for path", "NOT_FOUND", 404)
        duration = (time.time() - start) * 1000
        return ResponseWrapper.success(project, duration)
    except Exception as e:
        return ResponseWrapper.error(str(e), "PROJECT_DETECT_ERROR", 500)


@app.get("/project_list")
async def project_list(request: Request) -> Dict[str, Any]:
    """List all projects."""
    start = time.time()
    try:
        projects = request.app.state.engine.db.list_projects()
        duration = (time.time() - start) * 1000
        return ResponseWrapper.success({"projects": projects}, duration)
    except Exception as e:
        return ResponseWrapper.error(str(e), "PROJECT_LIST_ERROR", 500)


@app.post("/project_switch")
async def project_switch(request: Request) -> Dict[str, Any]:
    """Switch active project by locking it."""
    start = time.time()
    try:
        body = await request.json()
        project_id = body["project_id"]
        ok = request.app.state.engine.db.lock_project(project_id)
        if not ok:
            return ResponseWrapper.error("Project not found", "NOT_FOUND", 404)
        duration = (time.time() - start) * 1000
        return ResponseWrapper.success({"project_id": project_id, "locked": True}, duration)
    except Exception as e:
        return ResponseWrapper.error(str(e), "PROJECT_SWITCH_ERROR", 500)


# ============================================================================
# Session
# ============================================================================

@app.post("/session_start")
async def session_start(request: Request) -> Dict[str, Any]:
    """Start a new workflow session."""
    start = time.time()
    try:
        body = await request.json()
        project_id = body["project_id"]
        workflow_type = body.get("workflow_type", "new_project")
        default_rules = body.get("default_rules")
        sid = request.app.state.engine.start_session(project_id, workflow_type, default_rules)
        duration = (time.time() - start) * 1000
        return ResponseWrapper.success({"session_id": sid}, duration)
    except Exception as e:
        return ResponseWrapper.error(str(e), "SESSION_START_ERROR", 500)


@app.post("/session_resume")
async def session_resume(request: Request) -> Dict[str, Any]:
    """Resume the most recent pausable session for a project."""
    start = time.time()
    try:
        body = await request.json()
        project_id = body["project_id"]
        sid = request.app.state.engine.resume_session(project_id)
        interview = request.app.state.engine.session_status(sid)["interview"]
        duration = (time.time() - start) * 1000
        return ResponseWrapper.success({"session_id": sid, "interview": interview}, duration)
    except Exception as e:
        return ResponseWrapper.error(str(e), "SESSION_RESUME_ERROR", 500)


@app.get("/session_status")
async def session_status(request: Request, session_id: str) -> Dict[str, Any]:
    """Get comprehensive session status."""
    start = time.time()
    try:
        status = request.app.state.engine.session_status(session_id)
        duration = (time.time() - start) * 1000
        return ResponseWrapper.success(status, duration)
    except Exception as e:
        return ResponseWrapper.error(str(e), "SESSION_STATUS_ERROR", 500)


@app.get("/session_list")
async def session_list(request: Request, project_id: str | None = None) -> Dict[str, Any]:
    """List sessions, optionally filtered by project."""
    start = time.time()
    try:
        sessions = request.app.state.engine.db.list_sessions(project_id=project_id)
        duration = (time.time() - start) * 1000
        return ResponseWrapper.success({"sessions": sessions}, duration)
    except Exception as e:
        return ResponseWrapper.error(str(e), "SESSION_LIST_ERROR", 500)


# ============================================================================
# Interview
# ============================================================================

@app.post("/interview_question")
async def interview_question(request: Request) -> Dict[str, Any]:
    """Register an interview question (opens the interview; one open at a time)."""
    start = time.time()
    try:
        body = await request.json()
        result = request.app.state.engine.interview_question(
            body["session_id"], body["question"])
        duration = (time.time() - start) * 1000
        return ResponseWrapper.success(result, duration)
    except Exception as e:
        return ResponseWrapper.error(str(e), "INTERVIEW_QUESTION_ERROR", 500)


@app.post("/interview_answer")
async def interview_answer(request: Request) -> Dict[str, Any]:
    """Record (or revise) the user's answer to an interview question."""
    start = time.time()
    try:
        body = await request.json()
        result = request.app.state.engine.interview_answer(
            body["question_id"], body["answer"])
        duration = (time.time() - start) * 1000
        return ResponseWrapper.success(result, duration)
    except Exception as e:
        return ResponseWrapper.error(str(e), "INTERVIEW_ANSWER_ERROR", 500)


@app.post("/interview_complete")
async def interview_complete(request: Request) -> Dict[str, Any]:
    """Declare the interview complete; unblocks step_add."""
    start = time.time()
    try:
        body = await request.json()
        result = request.app.state.engine.interview_complete(body["session_id"])
        duration = (time.time() - start) * 1000
        return ResponseWrapper.success(result, duration)
    except Exception as e:
        return ResponseWrapper.error(str(e), "INTERVIEW_COMPLETE_ERROR", 500)


# ============================================================================
# Pipeline / Steps
# ============================================================================

@app.get("/step_current")
async def step_current(request: Request, session_id: str) -> Dict[str, Any]:
    """Get the current active or next pending step."""
    start = time.time()
    try:
        step = request.app.state.engine.current_step(session_id)
        if not step:
            return ResponseWrapper.success({"signal": "no_steps"}, (time.time() - start) * 1000)
        duration = (time.time() - start) * 1000
        return ResponseWrapper.success(step, duration)
    except Exception as e:
        return ResponseWrapper.error(str(e), "STEP_CURRENT_ERROR", 500)


@app.post("/step_set_feature")
async def step_set_feature(request: Request) -> Dict[str, Any]:
    """Validate and persist a Gherkin feature for a step (disk = truth)."""
    start = time.time()
    try:
        body = await request.json()
        result = request.app.state.engine.set_feature(
            body["step_id"], body["session_id"], body["content"],
            filename=body.get("filename"),
        )
        duration = (time.time() - start) * 1000
        return ResponseWrapper.success(result, duration)
    except Exception as e:
        return ResponseWrapper.error(str(e), "STEP_SET_FEATURE_ERROR", 500)


@app.get("/step_get_feature")
async def step_get_feature(request: Request, step_id: str, session_id: str) -> Dict[str, Any]:
    """Read a step's feature from disk, reporting drift and missing file."""
    start = time.time()
    try:
        result = request.app.state.engine.get_feature(step_id, session_id)
        duration = (time.time() - start) * 1000
        return ResponseWrapper.success(result, duration)
    except Exception as e:
        return ResponseWrapper.error(str(e), "STEP_GET_FEATURE_ERROR", 500)


@app.get("/step_validate_feature")
async def step_validate_feature(request: Request, step_id: str, session_id: str) -> Dict[str, Any]:
    """Dry-run validation: Gherkin syntax + step definitions."""
    start = time.time()
    try:
        result = request.app.state.engine.validate_feature(step_id, session_id)
        duration = (time.time() - start) * 1000
        return ResponseWrapper.success(result, duration)
    except Exception as e:
        return ResponseWrapper.error(str(e), "STEP_VALIDATE_FEATURE_ERROR", 500)


@app.post("/step_run_tests")
async def step_run_tests(request: Request) -> Dict[str, Any]:
    """Execute tests for a step via the configured adapter."""
    start = time.time()
    try:
        body = await request.json()
        step_id = body["step_id"]
        session_id = body["session_id"]
        result, drifted = request.app.state.engine.run_tests(step_id, session_id)
        duration = (time.time() - start) * 1000
        return ResponseWrapper.success({
            "passed": result.passed,
            "failed": result.failed,
            "coverage": result.coverage,
            "errors": result.errors,
            "feature_drifted": drifted,
        }, duration)
    except Exception as e:
        return ResponseWrapper.error(str(e), "STEP_RUN_TESTS_ERROR", 500)


@app.post("/step_complete")
async def step_complete(request: Request) -> Dict[str, Any]:
    """Attempt to complete a step by evaluating rules."""
    start = time.time()
    try:
        body = await request.json()
        step_id = body["step_id"]
        session_id = body["session_id"]
        action = request.app.state.engine.complete_step(step_id, session_id)
        duration = (time.time() - start) * 1000
        return ResponseWrapper.success({"action": action}, duration)
    except Exception as e:
        return ResponseWrapper.error(str(e), "STEP_COMPLETE_ERROR", 500)


@app.post("/step_skip")
async def step_skip(request: Request) -> Dict[str, Any]:
    """Skip a step with a reason."""
    start = time.time()
    try:
        body = await request.json()
        step_id = body["step_id"]
        session_id = body["session_id"]
        reason = body.get("reason", "")
        request.app.state.engine.skip_step(step_id, session_id, reason)
        duration = (time.time() - start) * 1000
        return ResponseWrapper.success({"step_id": step_id, "status": "skipped"}, duration)
    except Exception as e:
        return ResponseWrapper.error(str(e), "STEP_SKIP_ERROR", 500)


@app.get("/step_list")
async def step_list(request: Request, session_id: str) -> Dict[str, Any]:
    """List all steps for a session."""
    start = time.time()
    try:
        steps = request.app.state.engine.db.list_steps(session_id)
        duration = (time.time() - start) * 1000
        return ResponseWrapper.success({"steps": steps}, duration)
    except Exception as e:
        return ResponseWrapper.error(str(e), "STEP_LIST_ERROR", 500)


@app.post("/step_add")
async def step_add(request: Request) -> Dict[str, Any]:
    """Add a step to a session."""
    start = time.time()
    try:
        body = await request.json()
        session_id = body["session_id"]
        title = body["title"]
        description = body.get("description", "")
        order = body["order"]
        kwargs = {k: v for k, v in body.items()
                  if k not in ("session_id", "title", "description", "order")}
        step_id = request.app.state.engine.add_step(session_id, title, description, order, **kwargs)
        duration = (time.time() - start) * 1000
        return ResponseWrapper.success({"step_id": step_id}, duration)
    except Exception as e:
        return ResponseWrapper.error(str(e), "STEP_ADD_ERROR", 500)


@app.post("/step_remove")
async def step_remove(request: Request) -> Dict[str, Any]:
    """Remove a step."""
    start = time.time()
    try:
        body = await request.json()
        step_id = body["step_id"]
        ok = request.app.state.engine.db.remove_step(step_id)
        duration = (time.time() - start) * 1000
        return ResponseWrapper.success({"step_id": step_id, "removed": ok}, duration)
    except Exception as e:
        return ResponseWrapper.error(str(e), "STEP_REMOVE_ERROR", 500)


@app.post("/step_edit")
async def step_edit(request: Request) -> Dict[str, Any]:
    """Edit step fields."""
    start = time.time()
    try:
        body = await request.json()
        step_id = body.pop("step_id")
        request.app.state.engine.db.update_step(step_id, **body)
        duration = (time.time() - start) * 1000
        return ResponseWrapper.success({"step_id": step_id, "updated": True}, duration)
    except Exception as e:
        return ResponseWrapper.error(str(e), "STEP_EDIT_ERROR", 500)


@app.post("/step_reorder")
async def step_reorder(request: Request) -> Dict[str, Any]:
    """Reorder steps in a session."""
    start = time.time()
    try:
        body = await request.json()
        session_id = body["session_id"]
        step_ids = body["step_ids"]
        request.app.state.engine.db.reorder_steps(session_id, step_ids)
        duration = (time.time() - start) * 1000
        return ResponseWrapper.success({"session_id": session_id, "reordered": True}, duration)
    except Exception as e:
        return ResponseWrapper.error(str(e), "STEP_REORDER_ERROR", 500)


@app.get("/pipeline_view")
async def pipeline_view(request: Request, session_id: str) -> Dict[str, Any]:
    """Get pipeline view (session status with all steps)."""
    start = time.time()
    try:
        status = request.app.state.engine.session_status(session_id)
        duration = (time.time() - start) * 1000
        return ResponseWrapper.success(status, duration)
    except Exception as e:
        return ResponseWrapper.error(str(e), "PIPELINE_VIEW_ERROR", 500)


@app.post("/pipeline_set_rules")
async def pipeline_set_rules(request: Request) -> Dict[str, Any]:
    """Set default rules for a session."""
    start = time.time()
    try:
        body = await request.json()
        session_id = body["session_id"]
        default_rules = body["default_rules"]
        # Store rules as JSON in the session
        db = request.app.state.engine.db
        db.conn.execute(
            "UPDATE sessions SET default_rules=? WHERE id=?",
            (json.dumps(default_rules), session_id),
        )
        db.conn.commit()
        duration = (time.time() - start) * 1000
        return ResponseWrapper.success({"session_id": session_id, "rules_set": True}, duration)
    except Exception as e:
        return ResponseWrapper.error(str(e), "PIPELINE_SET_RULES_ERROR", 500)


# ============================================================================
# Introspection
# ============================================================================

@app.get("/pipeline_report")
async def pipeline_report(request: Request, session_id: str) -> Dict[str, Any]:
    """Get pipeline report with stats."""
    start = time.time()
    try:
        status = request.app.state.engine.session_status(session_id)
        duration = (time.time() - start) * 1000
        return ResponseWrapper.success(status, duration)
    except Exception as e:
        return ResponseWrapper.error(str(e), "PIPELINE_REPORT_ERROR", 500)


@app.get("/event_log")
async def event_log(request: Request, session_id: str, limit: int = 100) -> Dict[str, Any]:
    """Get event log for a session."""
    start = time.time()
    try:
        events = request.app.state.engine.db.list_events(session_id, limit)
        duration = (time.time() - start) * 1000
        return ResponseWrapper.success({"events": events}, duration)
    except Exception as e:
        return ResponseWrapper.error(str(e), "EVENT_LOG_ERROR", 500)


if __name__ == "__main__":
    import uvicorn
    uvicorn.run(app, host="127.0.0.1", port=8765)
