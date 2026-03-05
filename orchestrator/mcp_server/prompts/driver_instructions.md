# Driver Instructions

Always call `workflow_tick()` first. Execute exactly the single action returned by `workflow_tick()` and no other action. Repeat calling `workflow_tick()` after completing each returned action until it returns `{"type": "done"}`.

Allowed types returned by `workflow_tick()`:
- `need_tool`: call the specified tool with the provided args.
- `need_user_input`: present the closed question to the user, collect a short answer, and submit via `submit_via_tool`.
- `need_llm_step`: run the specified prompt (use MCP prompt path) and perform the expected tool calls listed under `expected`.
- `done`: workflow complete.
- `error`: stop and report the error.

Do not make nondeterministic choices; follow the driver's 'expected' field for which tool to call next.