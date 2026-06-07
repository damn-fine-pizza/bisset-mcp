"""Bisset v2 MCP Server -- STDIO proxy using JSON-RPC protocol.

Translates MCP tool calls into HTTP requests to workflow_server.
Exposes resources and prompts for Claude context.
"""
import json
import logging
import os
import sys
import time

from . import client as _client
from .prompts import PromptRegistry


def _setup_logging() -> logging.Logger:
    """Configure logging to file (never stdout/stderr — STDIO protocol)."""
    log_dir = os.path.join(os.path.dirname(__file__), "..", "..", "logs")
    os.makedirs(log_dir, exist_ok=True)
    log_file = os.path.join(log_dir, "mcp-server.log")

    handler = logging.FileHandler(log_file)
    handler.setFormatter(logging.Formatter(
        "%(asctime)s %(levelname)s %(message)s", datefmt="%Y-%m-%d %H:%M:%S"
    ))

    _logger = logging.getLogger("bisset-mcp")
    _logger.setLevel(logging.INFO)
    _logger.addHandler(handler)
    _logger.propagate = False
    return _logger


logger = _setup_logging()


class BissetMCPServer:
    """MCP protocol handler for Bisset v2."""

    def __init__(self):
        self.prompt_registry = PromptRegistry()
        self.tools = self._build_tools()
        self.resources = self._build_resources()

    def _build_tools(self) -> list[dict]:
        """Build MCP tool definitions for all v2 tools."""
        return [
            # Project
            {"name": "project_detect", "description": "Autodetect project from cwd",
             "inputSchema": {"type": "object", "properties": {"cwd": {"type": "string"}}, "required": ["cwd"]}},
            {"name": "project_create", "description": "Create new project and lock it",
             "inputSchema": {"type": "object", "properties": {
                 "name": {"type": "string"}, "path": {"type": "string"},
                 "test_runner": {"type": "string"}, "adapter": {"type": "string"},
                 "test_args": {"type": "string"}, "features_dir": {"type": "string"},
             }, "required": ["name", "path"]}},
            {"name": "project_list", "description": "List all projects",
             "inputSchema": {"type": "object", "properties": {}, "required": []}},
            {"name": "project_switch", "description": "Switch active project",
             "inputSchema": {"type": "object", "properties": {"project_id": {"type": "string"}}, "required": ["project_id"]}},
            # Session
            {"name": "session_start", "description": "Create session with workflow type",
             "inputSchema": {"type": "object", "properties": {
                 "project_id": {"type": "string"}, "workflow_type": {"type": "string"},
                 "default_rules": {"type": "array", "items": {"type": "object", "properties": {}}},
             }, "required": ["project_id"]}},
            {"name": "session_resume", "description": "Resume latest pausable session; reports interview state and pending question if any",
             "inputSchema": {"type": "object", "properties": {"project_id": {"type": "string"}}, "required": ["project_id"]}},
            {"name": "session_status", "description": "Get session status with steps and progress",
             "inputSchema": {"type": "object", "properties": {"session_id": {"type": "string"}}, "required": ["session_id"]}},
            {"name": "session_list", "description": "List sessions (cross-project ok)",
             "inputSchema": {"type": "object", "properties": {"project_id": {"type": "string"}}, "required": []}},
            # Interview
            {"name": "interview_question",
             "description": "Register an interview question Bisset-side before asking it (one open question at a time; reopens a completed interview)",
             "inputSchema": {"type": "object", "properties": {
                 "session_id": {"type": "string"}, "question": {"type": "string"},
             }, "required": ["session_id", "question"]}},
            {"name": "interview_answer",
             "description": "Record the user's answer to an interview question by id (re-answering an answered one revises it, with audit)",
             "inputSchema": {"type": "object", "properties": {
                 "question_id": {"type": "string"}, "answer": {"type": "string"},
             }, "required": ["question_id", "answer"]}},
            {"name": "interview_complete",
             "description": "Declare the interview complete (requires no open question and at least one answer); unblocks step_add",
             "inputSchema": {"type": "object", "properties": {
                 "session_id": {"type": "string"},
             }, "required": ["session_id"]}},
            # Analysis
            {"name": "analysis_submit",
             "description": "Submit the proposed pipeline from codebase analysis: ordered steps with optional Gherkin drafts. Re-submitting an open proposal revises it. Check `submitted` in the response: false means a draft failed Gherkin validation (per-step errors) and nothing was saved",
             "inputSchema": {"type": "object", "properties": {
                 "session_id": {"type": "string"},
                 "steps": {"type": "array", "items": {"type": "object", "properties": {
                     "title": {"type": "string"},
                     "description": {"type": "string"},
                     "feature_draft": {"type": "string"},
                 }, "required": ["title"]}},
             }, "required": ["session_id", "steps"]}},
            {"name": "analysis_view",
             "description": "View the session's analysis proposal (status + proposed steps with drafts)",
             "inputSchema": {"type": "object", "properties": {
                 "session_id": {"type": "string"},
             }, "required": ["session_id"]}},
            {"name": "analysis_approve",
             "description": "Approve the open analysis proposal: materializes real steps, writes feature drafts to disk and unblocks step_add. Requires no open interview. Call only on explicit human confirmation",
             "inputSchema": {"type": "object", "properties": {
                 "session_id": {"type": "string"},
             }, "required": ["session_id"]}},
            {"name": "analysis_discard",
             "description": "Discard the open analysis proposal and unblock manual step_add",
             "inputSchema": {"type": "object", "properties": {
                 "session_id": {"type": "string"},
             }, "required": ["session_id"]}},
            # Pipeline
            {"name": "step_current", "description": "Get current active step",
             "inputSchema": {"type": "object", "properties": {"session_id": {"type": "string"}}, "required": ["session_id"]}},
            {"name": "step_set_feature",
             "description": "Submit Gherkin content for a step; Bisset validates, writes to the project features dir and registers content + hash",
             "inputSchema": {"type": "object", "properties": {
                 "step_id": {"type": "string"}, "session_id": {"type": "string"},
                 "content": {"type": "string"}, "filename": {"type": "string"},
             }, "required": ["step_id", "session_id", "content"]}},
            {"name": "step_get_feature",
             "description": "Read the step's .feature from disk (truth); reports feature_drifted and file_missing",
             "inputSchema": {"type": "object", "properties": {
                 "step_id": {"type": "string"}, "session_id": {"type": "string"},
             }, "required": ["step_id", "session_id"]}},
            {"name": "step_validate_feature",
             "description": "Dry-run validation of the step's feature: syntax_ok, steps_defined, undefined_steps",
             "inputSchema": {"type": "object", "properties": {
                 "step_id": {"type": "string"}, "session_id": {"type": "string"},
             }, "required": ["step_id", "session_id"]}},
            {"name": "step_run_tests", "description": "Execute Gherkin tests for step",
             "inputSchema": {"type": "object", "properties": {
                 "step_id": {"type": "string"}, "session_id": {"type": "string"},
             }, "required": ["step_id", "session_id"]}},
            {"name": "step_complete", "description": "Attempt to close step (gate check + rules)",
             "inputSchema": {"type": "object", "properties": {
                 "step_id": {"type": "string"}, "session_id": {"type": "string"},
             }, "required": ["step_id", "session_id"]}},
            {"name": "step_skip", "description": "Skip step with reason",
             "inputSchema": {"type": "object", "properties": {
                 "step_id": {"type": "string"}, "session_id": {"type": "string"},
                 "reason": {"type": "string"},
             }, "required": ["step_id", "session_id", "reason"]}},
            {"name": "step_list", "description": "List all steps with status",
             "inputSchema": {"type": "object", "properties": {"session_id": {"type": "string"}}, "required": ["session_id"]}},
            {"name": "step_add", "description": "Add step to pipeline",
             "inputSchema": {"type": "object", "properties": {
                 "session_id": {"type": "string"}, "title": {"type": "string"},
                 "description": {"type": "string"}, "order": {"type": "integer"},
                 "feature_path": {"type": "string"}, "gate": {"type": "string"},
             }, "required": ["session_id", "title", "order"]}},
            {"name": "step_remove", "description": "Remove step (pending only)",
             "inputSchema": {"type": "object", "properties": {"step_id": {"type": "string"}}, "required": ["step_id"]}},
            {"name": "step_edit", "description": "Edit step fields",
             "inputSchema": {"type": "object", "properties": {
                 "step_id": {"type": "string"}, "title": {"type": "string"},
                 "description": {"type": "string"}, "gate": {"type": "string"},
                 "feature_path": {"type": "string"},
             }, "required": ["step_id"]}},
            {"name": "step_reorder", "description": "Reorder pipeline steps",
             "inputSchema": {"type": "object", "properties": {
                 "session_id": {"type": "string"}, "step_ids": {"type": "array", "items": {"type": "string"}},
             }, "required": ["session_id", "step_ids"]}},
            {"name": "pipeline_view", "description": "Full pipeline with status and dependencies",
             "inputSchema": {"type": "object", "properties": {"session_id": {"type": "string"}}, "required": ["session_id"]}},
            {"name": "pipeline_set_rules", "description": "Set session DSL rules",
             "inputSchema": {"type": "object", "properties": {
                 "session_id": {"type": "string"}, "default_rules": {"type": "array", "items": {"type": "object", "properties": {}}},
             }, "required": ["session_id", "default_rules"]}},
            # Introspection
            {"name": "pipeline_report", "description": "Pipeline report with stats",
             "inputSchema": {"type": "object", "properties": {"session_id": {"type": "string"}}, "required": ["session_id"]}},
            {"name": "event_log", "description": "Session audit trail",
             "inputSchema": {"type": "object", "properties": {
                 "session_id": {"type": "string"}, "limit": {"type": "integer"},
             }, "required": ["session_id"]}},
        ]

    def _build_resources(self) -> list[dict]:
        """Build MCP resource definitions."""
        return [
            {"uri": "project://current", "name": "Current project", "mimeType": "application/json"},
            {"uri": "session://current", "name": "Current session", "mimeType": "application/json"},
            {"uri": "pipeline://current", "name": "Pipeline steps with status", "mimeType": "application/json"},
            {"uri": "history://sessions", "name": "Previous sessions", "mimeType": "application/json"},
        ]

    def handle_request(self, request: dict) -> dict:
        """Handle MCP JSON-RPC request."""
        method = request.get("method")
        params = request.get("params", {})
        request_id = request.get("id")

        logger.info("-> %s id=%s", method, request_id)

        handlers = {
            "initialize": self._handle_initialize,
            "tools/list": self._handle_tools_list,
            "tools/call": self._handle_tool_call,
            "prompts/list": self._handle_prompts_list,
            "prompts/get": self._handle_prompt_get,
            "resources/list": self._handle_resources_list,
            "resources/read": self._handle_resource_read,
        }

        handler = handlers.get(method)
        if handler:
            response = handler(request_id, params)
            if "error" in response:
                logger.warning("<- %s ERROR: %s", method, response["error"].get("message"))
            else:
                logger.info("<- %s OK", method)
            return response
        logger.warning("<- unknown method: %s", method)
        return self._error_response(request_id, "method_not_found", f"Unknown: {method}")

    def _handle_initialize(self, request_id, params) -> dict:
        return {
            "jsonrpc": "2.0", "id": request_id,
            "result": {
                "protocolVersion": "2024-11-05",
                "capabilities": {
                    "tools": {"listChanged": True},
                    "prompts": {"listChanged": True},
                    "resources": {"listChanged": True},
                },
                "serverInfo": {"name": "Bisset MCP", "version": "2.0.0"},
            }
        }

    def _handle_tools_list(self, request_id, params) -> dict:
        return {"jsonrpc": "2.0", "id": request_id, "result": {"tools": self.tools}}

    def _handle_tool_call(self, request_id, params) -> dict:
        tool_name = params.get("name", "")
        arguments = params.get("arguments", {})
        logger.info("   tool=%s args=%s", tool_name, json.dumps(arguments, ensure_ascii=False))
        t0 = time.time()
        try:
            result = _client.call_tool(tool_name, arguments)
        except Exception as exc:
            logger.error("   tool=%s FAILED: %s (%.1fms)", tool_name, exc, (time.time() - t0) * 1000)
            return self._error_response(request_id, "backend_error", str(exc))
        logger.info("   tool=%s completed (%.1fms)", tool_name, (time.time() - t0) * 1000)
        return {"jsonrpc": "2.0", "id": request_id, "result": result}

    def _handle_prompts_list(self, request_id, params) -> dict:
        names = self.prompt_registry.list_prompts()
        prompts = [{"name": n, "description": f"Bisset {n.split('/')[-1]} prompt"} for n in names]
        return {"jsonrpc": "2.0", "id": request_id, "result": {"prompts": prompts}}

    def _handle_prompt_get(self, request_id, params) -> dict:
        name = params.get("name", "")
        context_args = params.get("arguments", {})
        tpl = self.prompt_registry.get_prompt(name)
        if not tpl:
            return self._error_response(request_id, "not_found", f"Prompt not found: {name}")
        text = tpl.render(db_vars={}, context_vars=context_args)
        return {
            "jsonrpc": "2.0", "id": request_id,
            "result": {"messages": [{"role": "user", "content": {"type": "text", "text": text}}]}
        }

    def _handle_resources_list(self, request_id, params) -> dict:
        return {"jsonrpc": "2.0", "id": request_id, "result": {"resources": self.resources}}

    def _handle_resource_read(self, request_id, params) -> dict:
        uri = params.get("uri", "")
        logger.info("   resource=%s", uri)
        # Map URIs to tool calls for live data
        uri_tool_map = {
            "project://current": ("project_list", {}),
            "session://current": ("session_list", {}),
            "pipeline://current": ("project_list", {}),
            "history://sessions": ("session_list", {}),
        }
        tool_info = uri_tool_map.get(uri)
        if tool_info:
            try:
                data = _client.call_tool(tool_info[0], tool_info[1])
                text = json.dumps(data)
            except Exception:
                text = json.dumps({"error": f"Could not fetch {uri}"})
        else:
            text = json.dumps({"error": f"Unknown resource: {uri}"})
        return {
            "jsonrpc": "2.0", "id": request_id,
            "result": {"contents": [{"uri": uri, "mimeType": "application/json", "text": text}]}
        }

    def _error_response(self, request_id, code: str, message: str) -> dict:
        return {
            "jsonrpc": "2.0", "id": request_id,
            "error": {"code": -32000, "message": message, "data": {"error_code": code}}
        }


def main():
    """Run Bisset MCP server on STDIO."""
    logger.info("Starting Bisset v2 MCP Server")
    server = BissetMCPServer()

    while True:
        try:
            line = sys.stdin.readline()
            if not line:
                break
            request = json.loads(line)
            response = server.handle_request(request)
            print(json.dumps(response, ensure_ascii=False))
            sys.stdout.flush()
        except json.JSONDecodeError as e:
            logger.error("JSON decode error: %s", e)
            error = {"jsonrpc": "2.0", "id": None, "error": {"code": -32700, "message": "Parse error"}}
            print(json.dumps(error))
            sys.stdout.flush()
        except Exception:
            logger.exception("Unexpected error")


if __name__ == "__main__":
    main()
