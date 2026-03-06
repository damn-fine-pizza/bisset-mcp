Driver schema

The deterministic driver is exposed as workflow_tick and returns a single JSON command describing the only valid next action. Schema (keys may be omitted when irrelevant):

{
  "type": "need_tool | need_user_input | need_llm_step | done | error",
  "reason": "string",
  "tool": "tool_name_if_need_tool",
  "args": { ... },
  "question": { "id": "Q1", "text": "..." },
  "submit_via_tool": "workflow_record_answer",
  "submit_args_schema": { "question_id": "...", "answer_text": "..." },
  "prompt_name": "roles/architect | phases/implementation_loop | ...",
  "expected": [ { "tool": "workflow_accept_task_result", "args": { ... } } ],
  "store_output_via_tool": "workflow_store_note",
  "store_args_schema": { "key": "...", "content": "..." },
  "task": { "id": "...", "title": "...", "details": "..." }
}

Phases/subphases

- interview: requirements interview (closed questions)
- execution: implementation phase; may use sub_phase 'phase_2_5_requirements' for validator
- done: workflow complete

How to run

1. Start workflow_server:
   python -m orchestrator.workflow_server
   or: uvicorn orchestrator.workflow_server.app:app --reload --port 8765
2. Start mcp_server (requires workflow_server running):
   python -m orchestrator.mcp_server
3. In Copilot CLI, use the MCP prompt/tool `workflow_tick()` as the single source of truth:
   - Call workflow_tick(), follow its returned action exactly.
   - For questions: present to user and submit via workflow_record_answer(question_id, answer_text).
   - For implementation tasks: implement, then call workflow_accept_task_result(...) with evidence.

Minimal test

- User asks Copilot: "Start project: <description>"
- Copilot calls workflow_tick() → sees need_tool workflow_new_session → calls it
- Driver next returns need_user_input with question → Copilot asks user and records answer via workflow_record_answer
- Loop continues until driver returns need_tool workflow_freeze_spec, then generates tasks
- Driver returns need_llm_step with task; Copilot implements and calls workflow_accept_task_result
- Driver eventually returns done
