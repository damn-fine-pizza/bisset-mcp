"""Bisset v2 MCP Server -- STDIO proxy using JSON-RPC protocol.

Translates MCP tool calls into HTTP requests to workflow_server.
Exposes resources and prompts for Claude context.
"""
import json
import logging
import sys

from . import client as _client
from .prompts import PromptRegistry

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger("bisset-mcp-server")


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
             "inputSchema": {"type": "object", "properties": {}}},
            {"name": "project_switch", "description": "Switch active project",
             "inputSchema": {"type": "object", "properties": {"project_id": {"type": "string"}}, "required": ["project_id"]}},
            # Session
            {"name": "session_start", "description": "Create session with workflow type",
             "inputSchema": {"type": "object", "properties": {
                 "project_id": {"type": "string"}, "workflow_type": {"type": "string"},
                 "default_rules": {"type": "array", "items": {"type": "object", "properties": {}}},
             }, "required": ["project_id"]}},
            {"name": "session_resume", "description": "Resume latest pausable session",
             "inputSchema": {"type": "object", "properties": {"project_id": {"type": "string"}}, "required": ["project_id"]}},
            {"name": "session_status", "description": "Get session status with steps and progress",
             "inputSchema": {"type": "object", "properties": {"session_id": {"type": "string"}}, "required": ["session_id"]}},
            {"name": "session_list", "description": "List sessions (cross-project ok)",
             "inputSchema": {"type": "object", "properties": {"project_id": {"type": "string"}}}},
            # Pipeline
            {"name": "step_current", "description": "Get current active step",
             "inputSchema": {"type": "object", "properties": {"session_id": {"type": "string"}}, "required": ["session_id"]}},
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
            return handler(request_id, params)
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
        try:
            result = _client.call_tool(tool_name, arguments)
        except Exception as exc:
            return self._error_response(request_id, "backend_error", str(exc))
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
