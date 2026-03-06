"""
Claude MCP Server - Independent implementation for Claude integration.
STDIO proxy using Claude SDK MCP protocol.
"""
import json
import logging
import time
import sys
from typing import Any

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger('claude-mcp-server')


class ClaudeServerProtocol:
    """MCP protocol handler for Claude SDK."""

    def __init__(self):
        self.tools = self._build_tools()
        self.prompts = self._build_prompts()
        self.resources = self._build_resources()

    def _build_tools(self) -> list[dict]:
        """Build all 26+ tool definitions."""
        return [
            {
                "name": "workflow_new_session",
                "description": "Create a new Bisset project session.",
                "input_schema": {
                    "type": "object",
                    "properties": {
                        "name": {"type": "string"}
                    }
                }
            },
            {
                "name": "workflow_switch_session",
                "description": "Switch to an existing session.",
                "input_schema": {
                    "type": "object",
                    "properties": {
                        "session_id": {"type": "string"}
                    },
                    "required": ["session_id"]
                }
            },
            {
                "name": "workflow_detect_session",
                "description": "Detect session for a project path.",
                "input_schema": {
                    "type": "object",
                    "properties": {
                        "cwd": {"type": "string"}
                    },
                    "required": ["cwd"]
                }
            },
            {
                "name": "workflow_start",
                "description": "Start workflow with project metadata.",
                "input_schema": {
                    "type": "object",
                    "properties": {
                        "project_meta": {"type": "object"}
                    },
                    "required": ["project_meta"]
                }
            },
            {
                "name": "workflow_get_state",
                "description": "Get current workflow state.",
                "input_schema": {"type": "object"}
            },
            {
                "name": "workflow_next_question",
                "description": "Get next interview question.",
                "input_schema": {"type": "object"}
            },
            {
                "name": "workflow_record_answer",
                "description": "Record an interview answer.",
                "input_schema": {
                    "type": "object",
                    "properties": {
                        "question_id": {"type": "string"},
                        "answer_text": {"type": "string"}
                    },
                    "required": ["question_id", "answer_text"]
                }
            },
            {
                "name": "workflow_freeze_spec",
                "description": "Freeze the specification.",
                "input_schema": {"type": "object"}
            },
            {
                "name": "workflow_next_task",
                "description": "Get next task to implement.",
                "input_schema": {"type": "object"}
            },
            {
                "name": "workflow_accept_task_result",
                "description": "Accept completed task.",
                "input_schema": {
                    "type": "object",
                    "properties": {
                        "task_id": {"type": "string"},
                        "summary": {"type": "string"},
                        "artifacts_changed": {"type": "array"},
                        "tests_run": {"type": "array"},
                        "test_results": {"type": "object"}
                    },
                    "required": ["task_id", "summary"]
                }
            },
            {
                "name": "workflow_report",
                "description": "Get progress report.",
                "input_schema": {"type": "object"}
            },
            {
                "name": "workflow_is_done",
                "description": "Check if workflow is complete.",
                "input_schema": {"type": "object"}
            },
            {
                "name": "workflow_list_sessions",
                "description": "List all sessions.",
                "input_schema": {"type": "object"}
            },
            {
                "name": "workflow_list_tasks",
                "description": "List all tasks.",
                "input_schema": {
                    "type": "object",
                    "properties": {
                        "status": {"type": "string"}
                    }
                }
            },
            {
                "name": "workflow_list_questions",
                "description": "List all questions.",
                "input_schema": {
                    "type": "object",
                    "properties": {
                        "answered": {"type": "boolean"}
                    }
                }
            },
            {
                "name": "workflow_run_tests",
                "description": "Run tests for a task.",
                "input_schema": {
                    "type": "object",
                    "properties": {
                        "task_id": {"type": "string"}
                    },
                    "required": ["task_id"]
                }
            },
            {
                "name": "workflow_add_task",
                "description": "Add a new task.",
                "input_schema": {
                    "type": "object",
                    "properties": {
                        "task_id": {"type": "string"},
                        "title": {"type": "string"},
                        "description": {"type": "string"},
                        "acceptance_criteria": {"type": "string"},
                        "negative_acceptance_criteria": {"type": "string"}
                    },
                    "required": ["task_id", "title"]
                }
            },
            {
                "name": "workflow_advance_phase",
                "description": "Advance workflow phase.",
                "input_schema": {
                    "type": "object",
                    "properties": {
                        "signal": {"type": "string"}
                    },
                    "required": ["signal"]
                }
            },
            {
                "name": "workflow_store_proposal",
                "description": "Store architecture proposal.",
                "input_schema": {
                    "type": "object",
                    "properties": {
                        "paradigm": {"type": "string"},
                        "content": {"type": "string"}
                    },
                    "required": ["paradigm", "content"]
                }
            },
            {
                "name": "workflow_list_proposals",
                "description": "List architecture proposals.",
                "input_schema": {"type": "object"}
            },
            {
                "name": "workflow_status",
                "description": "Get comprehensive status.",
                "input_schema": {"type": "object"}
            },
            {
                "name": "workflow_store_note",
                "description": "Store a note.",
                "input_schema": {
                    "type": "object",
                    "properties": {
                        "key": {"type": "string"},
                        "content": {"type": "string"}
                    },
                    "required": ["key", "content"]
                }
            },
            {
                "name": "workflow_bootstrap_project",
                "description": "Bootstrap project configuration.",
                "input_schema": {
                    "type": "object",
                    "properties": {
                        "cwd": {"type": "string"},
                        "autodetect": {"type": "boolean"}
                    },
                    "required": ["cwd"]
                }
            },
            {
                "name": "workflow_run_until_blocked",
                "description": "Run autonomous loop.",
                "input_schema": {
                    "type": "object",
                    "properties": {
                        "max_iterations": {"type": "integer"},
                        "max_minutes": {"type": "number"}
                    }
                }
            },
            {
                "name": "workflow_get_events",
                "description": "Get event log.",
                "input_schema": {
                    "type": "object",
                    "properties": {
                        "limit": {"type": "integer"}
                    }
                }
            }
        ]

    def _build_prompts(self) -> dict:
        """Build prompt definitions."""
        return {
            "phases/requirements_interview": "Interview phase guidelines",
            "phases/design_review": "Design review prompt",
            "phases/implementation_loop": "Implementation prompt",
            "roles/architect": "Architect role",
            "roles/product_owner": "Product owner role",
            "roles/tech_lead": "Tech lead role",
            "roles/test_engineer": "Test engineer role",
            "roles/build_engineer": "Build engineer role"
        }

    def _build_resources(self) -> dict:
        """Build resource definitions."""
        return {
            "spec://current": "Current specification",
            "constraints://current": "Project constraints",
            "decisions://adr-index": "Architecture decisions",
            "plan://workbreakdown": "Work breakdown"
        }

    def handle_request(self, request: dict) -> dict:
        """Handle MCP JSON-RPC request."""
        method = request.get("method")
        params = request.get("params", {})
        request_id = request.get("id")

        if method == "initialize":
            return self._handle_initialize(request_id)
        elif method == "tools/list":
            return self._handle_tools_list(request_id)
        elif method == "tools/call":
            return self._handle_tool_call(request_id, params)
        elif method == "prompts/list":
            return self._handle_prompts_list(request_id)
        elif method == "prompts/get":
            return self._handle_prompt_get(request_id, params)
        elif method == "resources/list":
            return self._handle_resources_list(request_id)
        elif method == "resources/read":
            return self._handle_resource_read(request_id, params)
        else:
            return self._error_response(request_id, "method_not_found", f"Unknown: {method}")

    def _handle_initialize(self, request_id: str) -> dict:
        """Handle initialize."""
        return {
            "jsonrpc": "2.0",
            "id": request_id,
            "result": {
                "protocolVersion": "2024-11-05",
                "capabilities": {
                    "tools": {"listChanged": True},
                    "prompts": {"listChanged": True},
                    "resources": {"listChanged": True}
                },
                "serverInfo": {
                    "name": "BissetMCP Claude Orchestrator",
                    "version": "1.0.0"
                }
            }
        }

    def _handle_tools_list(self, request_id: str) -> dict:
        """Handle tools/list."""
        return {
            "jsonrpc": "2.0",
            "id": request_id,
            "result": {"tools": self.tools}
        }

    def _handle_tool_call(self, request_id: str, params: dict) -> dict:
        """Forward tools/call to the workflow_server via HTTP."""
        from . import client as _client

        tool_name = params.get("name", "")
        arguments = params.get("arguments", {})

        try:
            result = _client.call_tool(tool_name, arguments)
        except Exception as exc:
            return self._error_response(request_id, "backend_error", str(exc))

        # result is already in Claude SDK TextContent format from the workflow_server
        return {
            "jsonrpc": "2.0",
            "id": request_id,
            "result": result,
        }

    def _handle_prompts_list(self, request_id: str) -> dict:
        """Handle prompts/list."""
        prompts = [{"name": name, "description": desc} for name, desc in self.prompts.items()]
        return {
            "jsonrpc": "2.0",
            "id": request_id,
            "result": {"prompts": prompts}
        }

    def _handle_prompt_get(self, request_id: str, params: dict) -> dict:
        """Handle prompts/get — fetch from workflow_server."""
        from . import client as _client

        prompt_name = params.get("name", "")
        try:
            data = _client.get_prompt(prompt_name)
            # data is a ResponseWrapper dict; extract the text content
            text = data.get("content", [{}])[0].get("text", "")
        except Exception:
            text = self.prompts.get(prompt_name, f"# {prompt_name}\n(not found)")

        return {
            "jsonrpc": "2.0",
            "id": request_id,
            "result": {"messages": [{"role": "user", "content": text}]}
        }

    def _handle_resources_list(self, request_id: str) -> dict:
        """Handle resources/list."""
        resources = [
            {"uri": uri, "name": name, "mimeType": "text/markdown"}
            for uri, name in self.resources.items()
        ]
        return {
            "jsonrpc": "2.0",
            "id": request_id,
            "result": {"resources": resources}
        }

    def _handle_resource_read(self, request_id: str, params: dict) -> dict:
        """Handle resources/read."""
        uri = params.get("uri")
        return {
            "jsonrpc": "2.0",
            "id": request_id,
            "result": {
                "contents": [{"uri": uri, "mimeType": "text/markdown", "text": "Content"}]
            }
        }

    def _error_response(self, request_id: str, code: str, message: str) -> dict:
        """Return error response."""
        return {
            "jsonrpc": "2.0",
            "id": request_id,
            "error": {"code": -32000, "message": message, "data": {"error_code": code}}
        }


def main():
    """Run Claude MCP server on STDIO."""
    logger.info("Starting Claude MCP Server")
    protocol = ClaudeServerProtocol()

    while True:
        try:
            line = sys.stdin.readline()
            if not line:
                break

            request = json.loads(line)
            response = protocol.handle_request(request)
            print(json.dumps(response, ensure_ascii=False))
            sys.stdout.flush()
        except json.JSONDecodeError as e:
            logger.error(f"JSON decode error: {e}")
            error = {
                "jsonrpc": "2.0",
                "id": None,
                "error": {"code": -32700, "message": "Parse error"}
            }
            print(json.dumps(error))
            sys.stdout.flush()
        except Exception as e:
            logger.exception("Unexpected error")


if __name__ == "__main__":
    main()
