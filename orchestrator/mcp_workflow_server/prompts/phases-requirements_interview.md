# Phase: Requirements Interview

Systematically call `workflow_next_question()` and present each question to the user.
Record each answer with `workflow_record_answer(question_id, answer_text)`.
When `workflow_next_question()` returns `done: true`, call `workflow_freeze_spec()`.
Do not skip questions. Do not invent answers.
