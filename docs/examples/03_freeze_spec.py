"""
Example 03: Freeze the specification
======================================
After all interview questions are answered, freeze the spec to advance the
workflow to the architecture phase. Demonstrates spec retrieval too.

Run:
    python docs/examples/03_freeze_spec.py <session_id>
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


def main(session_id: str):
    print(f"Freezing spec for session: {session_id}\n{'─' * 40}")

    # ── Pre-flight: check current phase ──────────────────────────────────────
    status = unwrap(requests.get(f"{BASE_URL}/workflow_status/{session_id}"))
    print(f"Current phase : {status['phase']}")
    if status["phase"] not in ("interview", "validation"):
        print("⚠  Spec already frozen or phase advanced. Continuing anyway.")

    # ── Verify all questions are answered ─────────────────────────────────────
    listing = unwrap(requests.get(f"{BASE_URL}/workflow_list_questions/{session_id}"))
    questions = listing["questions"]
    unanswered = [q for q in questions if not q["answered"]]

    if unanswered:
        print(f"\n✗ {len(unanswered)} question(s) still unanswered:")
        for q in unanswered:
            print(f"  [{q['id']}] {q['text']}")
        print("\nRun 02_interview.py first.")
        sys.exit(1)

    print(f"  {len(questions)}/{len(questions)} questions answered — ready to freeze")

    # ── Freeze the spec ───────────────────────────────────────────────────────
    result = unwrap(requests.post(f"{BASE_URL}/workflow_freeze_spec/{session_id}"))
    print(f"\nSpec signal   : {result['signal']}")

    # ── Confirm phase advanced ────────────────────────────────────────────────
    status_after = unwrap(requests.get(f"{BASE_URL}/workflow_status/{session_id}"))
    print(f"Phase after   : {status_after['phase']}")
    assert status_after["phase"] == "architecture", "Expected phase to be 'architecture'"

    # ── Retrieve and display the frozen spec ──────────────────────────────────
    spec = unwrap(requests.get(f"{BASE_URL}/workflow_get_spec/{session_id}"))
    print(f"\nFrozen at     : {spec.get('frozen_at'):.2f}")
    print(f"Q&A count     : {len(spec['questions'])}")
    print("\nSpec preview:")
    for i, q in enumerate(spec["questions"][:3], 1):
        print(f"  {i}. Q: {q['text'][:60]}...")
        print(f"     A: {(q['answer'] or '')[:60]}...")

    return session_id


if __name__ == "__main__":
    if len(sys.argv) < 2:
        print("Usage: python 03_freeze_spec.py <session_id>", file=sys.stderr)
        sys.exit(1)

    main(sys.argv[1])
    print(f"\nNext step: python docs/examples/04_architecture.py {sys.argv[1]}")
