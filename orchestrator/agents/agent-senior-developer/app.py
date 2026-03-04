from flask import Flask, request, jsonify
import os
from openai import OpenAI

ROLE = "Senior Backend Developer"
MODEL = os.environ.get('LLM_MODEL', 'gpt-4o-mini')
client = OpenAI(api_key=os.environ.get('OPENAI_API_KEY', ''))
app = Flask(__name__)

SYSTEM_PROMPT = """You are a Senior Backend Developer in a Scrum team.
Based on the architecture, DB schema and API contract, produce a backend implementation document in markdown that includes:
- Module/service structure with file tree
- Core data models / DTOs (Python dataclasses or TypeScript interfaces, match the chosen tech stack)
- Implementation of the 3 most critical API endpoints (full working code, not pseudocode)
- Database access layer (ORM models or raw queries)
- Input validation and error handling patterns
- Unit test examples for the critical business logic
Write clean, production-quality code with docstrings."""

FIX_SYSTEM_PROMPT = """You are a Senior Backend Developer fixing failing Gherkin/behave tests.
You will receive:
1. The list of failing test scenarios with error messages
2. The existing implementation context

Produce ONLY the code changes needed to fix the failing tests. Format your response as markdown with:
- A brief explanation of what is wrong
- The exact file(s) to create or modify with full file content (use ```python fences with the filename as comment)

Do NOT rewrite working code. Focus only on what makes the failing tests pass."""


@app.route('/webhook', methods=['POST'])
def webhook():
    payload = request.json or {}
    mode = payload.get('mode', 'full')
    print(f"[{ROLE}] processing task (mode={mode})")

    if mode == 'fix':
        failing_tests = payload.get('failing_tests', [])
        coverage_pct = payload.get('coverage_pct', 0)
        parts = ["# Failing Gherkin Tests\n"]
        for t in failing_tests:
            parts.append(f"## {t.get('scenario', 'unknown')}\n```\n{t.get('error', '')}\n```")
        parts.append("\n# Existing Implementation Context\n")
        for t in payload.get('context', []):
            parts.append(f"\n## {t['by']}\n{t.get('output', '')}")
        parts.append(f"\n\nCurrent coverage: {coverage_pct}%. Fix the failing tests to reach 80%+ coverage.")
        user_msg = "\n".join(parts)
        system = FIX_SYSTEM_PROMPT
        max_tokens = 3000
    else:
        parts = [f"# Project: {payload.get('project', '')}"]
        for t in payload.get('context', []):
            parts.append(f"\n## {t['by']}\n{t.get('output', '')}")
        user_msg = "\n".join(parts) + f"\n\nNow produce your full contribution as {ROLE}."
        system = SYSTEM_PROMPT
        max_tokens = 2500

    try:
        resp = client.chat.completions.create(
            model=MODEL,
            messages=[
                {"role": "system", "content": system},
                {"role": "user", "content": user_msg},
            ],
            max_tokens=max_tokens,
        )
        output = resp.choices[0].message.content
    except Exception as e:
        output = f"[LLM error: {e}]"
    print(f"[{ROLE}] done")
    return jsonify({'status': 'ok', 'role': ROLE, 'output': output, 'mode': mode})


if __name__ == '__main__':
    app.run(host='0.0.0.0', port=int(os.environ.get('PORT', 8000)))
