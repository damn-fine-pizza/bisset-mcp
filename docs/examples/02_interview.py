"""
Example 02: Run the interview phase
====================================
Walks through all interview questions, recording answers one by one.
Questions are returned in order_index order. The loop exits when the server
signals `interview_complete`.

Run:
    python docs/examples/02_interview.py <session_id>
    # or omit session_id to auto-detect
"""

import json
import sys
import requests

BASE_URL = "http://localhost:8765"


def unwrap(response: requests.Response) -> dict:
    response.raise_for_status()
    body = response.json()
    if body.get("is_error"):
        error_text = body["content"][0]["text"]
        error_data = json.loads(error_text)
        raise RuntimeError(f"{error_data.get('error')} ({error_data.get('code')})")
    return json.loads(body["content"][0]["text"])


# Hard-coded answers for the demo — in production these come from the LLM.
DEMO_ANSWERS = {
    "default": "This is a demo answer for automated testing.",
}

REAL_ANSWERS = [
    "A task management web application with user authentication, projects, and deadlines.",
    "Individual developers and small teams (2–10 people).",
    "REST API (FastAPI) + React frontend + PostgreSQL database.",
    "Mobile-friendly web app only; no native apps required.",
    "OAuth2 via GitHub; no custom password login needed.",
    "Public SaaS — multi-tenant with per-user data isolation.",
    "CI/CD via GitHub Actions; deploy to Fly.io or Railway.",
    "English only; UTC timestamps; no i18n required initially.",
]


def main(session_id: str):
    print(f"Interview for session: {session_id}\n{'─' * 40}")

    # Start the interview — get the first question
    result = unwrap(requests.post(f"{BASE_URL}/workflow_start_interview/{session_id}"))

    answer_index = 0

    while True:
        # Check for completion signal
        if result.get("signal") == "interview_complete":
            print("\n✓ Interview complete!")
            break

        question_id = result["id"]
        question_text = result["text"]
        print(f"\n[Q] {question_text}")

        # Pick an answer (cycled from our demo list)
        answer = REAL_ANSWERS[answer_index % len(REAL_ANSWERS)]
        answer_index += 1
        print(f"[A] {answer}")

        # Record the answer
        unwrap(
            requests.post(
                f"{BASE_URL}/workflow_record_answer/{session_id}/{question_id}",
                params={"answer": answer},
            )
        )

        # Get the next question
        result = unwrap(requests.get(f"{BASE_URL}/workflow_next_question/{session_id}"))

    # ── Show summary ──────────────────────────────────────────────────────────
    listing = unwrap(requests.get(f"{BASE_URL}/workflow_list_questions/{session_id}"))
    questions = listing["questions"]
    answered = sum(1 for q in questions if q["answered"])
    print(f"\nSummary: {answered}/{len(questions)} questions answered")

    return session_id


if __name__ == "__main__":
    if len(sys.argv) < 2:
        # Auto-detect most recent session
        import requests as _r
        body = _r.get(f"{BASE_URL}/workflow_detect_session").json()
        sid = json.loads(body["content"][0]["text"])["id"]
    else:
        sid = sys.argv[1]

    main(sid)
    print(f"\nNext step: python docs/examples/03_freeze_spec.py {sid}")
