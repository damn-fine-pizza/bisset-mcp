from flask import Flask, request, jsonify
import os
import pathlib
from openai import OpenAI

ROLE = "Software Architect"
MODEL = os.environ.get('LLM_MODEL', 'gpt-4o-mini')
USE_LLM = os.environ.get('USE_LLM','false').lower() == 'true'
PROMPTS_DIR = os.environ.get('PROMPTS_DIR','./prompts')
client = OpenAI(api_key=os.environ.get('OPENAI_API_KEY', '')) if USE_LLM else None
app = Flask(__name__)

SYSTEM_PROMPT = """You are a Software Architect in a Scrum team.
Based on the project requirements, DB schema and UX flows, produce an architecture document in markdown that includes:
- System architecture overview (components diagram in ASCII)
- Tech stack selection with rationale (backend, frontend, DB, infra)
- REST API contract: list of endpoints with method, path, request body, response shape
- Authentication / authorisation strategy
- Non-functional requirements: scalability approach, security considerations, observability
- Folder/module structure for both backend and frontend repos
Be opinionated and specific."""


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
