from flask import Flask, request, jsonify
import os
import pathlib
from openai import OpenAI

ROLE = "Senior Database Engineer"
MODEL = os.environ.get('LLM_MODEL', 'gpt-4o-mini')
USE_LLM = os.environ.get('USE_LLM','false').lower() == 'true'
PROMPTS_DIR = os.environ.get('PROMPTS_DIR','./prompts')
client = OpenAI(api_key=os.environ.get('OPENAI_API_KEY', '')) if USE_LLM else None
app = Flask(__name__)

SYSTEM_PROMPT = """You are a Senior Database Engineer in a Scrum team.
Based on the user stories, UX flows and project requirements, produce a database design document in markdown that includes:
- Entity-Relationship diagram (textual/ASCII notation)
- Full SQL DDL (CREATE TABLE statements) with proper types, constraints, and foreign keys
- Indexes strategy (which columns to index and why)
- Seed data examples for the main tables
- Migration strategy notes
- Any caching considerations (Redis keys, TTL strategy if relevant)
Use PostgreSQL syntax. Be precise."""


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
