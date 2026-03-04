# Phase: Implementation Loop

Call `workflow_next_task()` to get the current task.
Implement it. Then call `workflow_accept_task_result(task_id, summary, artifacts_changed, tests_run, test_results)`.
Repeat until `workflow_is_done()` returns `done: true`.
Do not ask the user new questions during this phase.
