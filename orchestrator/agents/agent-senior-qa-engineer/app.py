from flask import Flask, request, jsonify
import os
import pathlib
from openai import OpenAI

ROLE = "Senior QA Engineer"
MODEL = os.environ.get('LLM_MODEL', 'gpt-4o-mini')
USE_LLM = os.environ.get('USE_LLM','false').lower() == 'true'
PROMPTS_DIR = os.environ.get('PROMPTS_DIR','./prompts')
client = OpenAI(api_key=os.environ.get('OPENAI_API_KEY', '')) if USE_LLM else None
app = Flask(__name__)

SYSTEM_PROMPT = """You are a Senior QA Engineer in a Scrum team.
Based on the project requirements, user stories, and implementation details, produce a comprehensive test plan in markdown that includes:
- Test strategy overview
- Functional test cases (happy path and negative cases) for each user story
- Edge cases and boundary conditions
- Integration tests covering key API endpoints and data flows
- Performance test scenarios (load, stress, and soak tests)
- Acceptance criteria validation checklist
Be thorough and developer-ready."""


@app.route('/webhook', methods=['POST'])
def webhook():
    payload = request.json or {}
    print(f"[{ROLE}] processing task")
    parts = [f"# Project: {payload.get('project', '')}"]
    for t in payload.get('context', []):
        parts.append(f"\n## {t['by']}\n{t.get('output', '')}")
    user_msg = "\n".join(parts) + f"\n\nNow produce your full contribution as {ROLE}."
    if not USE_LLM:
        p = pathlib.Path(PROMPTS_DIR)/f"{ROLE}.md"
        output = p.read_text() if p.exists() else f"# {ROLE} output\n\n(No prompt template found)"
    else:
        try:
            resp = client.chat.completions.create(
                model=MODEL,
                messages=[
                    {"role": "system", "content": SYSTEM_PROMPT},
                    {"role": "user", "content": user_msg},
                ],
                max_tokens=2000,
            )
            output = resp.choices[0].message.content
        except Exception as e:
            output = f"[LLM error: {e}]"
    print(f"[{ROLE}] done")
    return jsonify({'status': 'ok', 'role': ROLE, 'output': output})


if __name__ == '__main__':
    app.run(host='0.0.0.0', port=int(os.environ.get('PORT', 8000)))
