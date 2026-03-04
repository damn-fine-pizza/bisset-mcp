from flask import Flask, request, jsonify
import os
import json
from openai import OpenAI

ROLE = "Senior QA Engineer"
MODEL = os.environ.get('LLM_MODEL', 'gpt-4o-mini')
client = OpenAI(api_key=os.environ.get('OPENAI_API_KEY', ''))
app = Flask(__name__)

SYSTEM_PROMPT = """You are a Senior QA Engineer in a Scrum team.
Based on the project requirements, user stories, and implementation details, produce ONLY a valid JSON object (no markdown fences, no prose outside the JSON) with this exact structure:

{
  "features": [
    {
      "filename": "example.feature",
      "content": "Feature: ...\\n  Scenario: ...\\n    Given ...\\n    When ...\\n    Then ..."
    }
  ],
  "steps": [
    {
      "filename": "steps/example_steps.py",
      "content": "from behave import given, when, then\\n\\n@given('...')\\ndef step_impl(context):\\n    pass"
    }
  ],
  "summary": "Brief description of what is tested"
}

Rules:
- .feature files must be valid Gherkin (Feature, Scenario, Given/When/Then)
- step definitions must be valid Python for behave (@given, @when, @then decorators)
- Cover ALL user stories from the backlog with happy path, negative cases, and edge cases
- Steps must import the actual production code (e.g. from src.module import Class)
- Output ONLY the JSON object, nothing else."""


@app.route('/webhook', methods=['POST'])
def webhook():
    payload = request.json or {}
    print(f"[{ROLE}] processing task")
    parts = [f"# Project: {payload.get('project', '')}"]
    for t in payload.get('context', []):
        parts.append(f"\n## {t['by']}\n{t.get('output', '')}")
    user_msg = "\n".join(parts) + f"\n\nNow produce your full contribution as {ROLE}."
    try:
        resp = client.chat.completions.create(
            model=MODEL,
            messages=[
                {"role": "system", "content": SYSTEM_PROMPT},
                {"role": "user", "content": user_msg},
            ],
            max_tokens=3000,
            response_format={"type": "json_object"},
        )
        raw = resp.choices[0].message.content
        gherkin_data = json.loads(raw)
    except Exception as e:
        gherkin_data = {"features": [], "steps": [], "summary": f"[LLM error: {e}]"}
    print(f"[{ROLE}] done — {len(gherkin_data.get('features', []))} features, {len(gherkin_data.get('steps', []))} step files")
    return jsonify({'status': 'ok', 'role': ROLE, 'output': json.dumps(gherkin_data), 'gherkin': gherkin_data})


if __name__ == '__main__':
    app.run(host='0.0.0.0', port=int(os.environ.get('PORT', 8000)))
