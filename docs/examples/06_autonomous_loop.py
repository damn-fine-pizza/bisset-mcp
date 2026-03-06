"""
Example 06: Autonomous end-to-end loop
========================================
Runs all five phases in sequence without human intervention:
  1. Create session
  2. Run interview (demo answers)
  3. Freeze spec
  4. Store proposals + inject tasks
  5. Implement all tasks
  6. Report final status

This demonstrates how a fully autonomous Bisset run looks from the outside.
Background jobs (async_mode=True) are used in this example to show polling.

Run:
    python docs/examples/06_autonomous_loop.py
"""

import json
import sys
import time
import requests

BASE_URL = "http://localhost:8765"

# ─── Helpers ─────────────────────────────────────────────────────────────────

def unwrap(response: requests.Response) -> dict:
    response.raise_for_status()
    body = response.json()
    if body.get("is_error"):
        error_text = body["content"][0]["text"]
        error_data = json.loads(error_text)
        raise RuntimeError(f"[{error_data.get('code')}] {error_data.get('error')}")
    return json.loads(body["content"][0]["text"])


def poll_job(session_id: str, job_id: str, timeout: int = 120) -> dict:
    """Poll a background job until it completes or times out."""
    deadline = time.time() + timeout
    while time.time() < deadline:
        job = unwrap(requests.get(f"{BASE_URL}/workflow_get_job_status/{session_id}/{job_id}"))
        if job["status"] in ("completed", "failed"):
            return job
        print(f"    … job {job_id} status={job['status']}, waiting…")
        time.sleep(2)
    raise TimeoutError(f"Job {job_id} did not complete within {timeout}s")


# ─── Phase implementations ────────────────────────────────────────────────────

DEMO_ANSWERS = [
    "A multi-tenant project management SaaS.",
    "Small engineering teams (3–15 developers).",
    "REST API (FastAPI) + React frontend.",
    "Web only; mobile PWA later.",
    "OAuth2 via GitHub.",
    "Multi-tenant; each team has isolated data.",
    "GitHub Actions + Docker; deploy to Fly.io.",
    "English only; UTC timestamps.",
]


def phase_interview(session_id: str):
    print("\n[Phase 1/5] Interview")
    result = unwrap(requests.post(f"{BASE_URL}/workflow_start_interview/{session_id}"))
    i = 0
    while result.get("signal") != "interview_complete":
        qid = result["id"]
        answer = DEMO_ANSWERS[i % len(DEMO_ANSWERS)]
        unwrap(requests.post(
            f"{BASE_URL}/workflow_record_answer/{session_id}/{qid}",
            params={"answer": answer},
        ))
        i += 1
        result = unwrap(requests.get(f"{BASE_URL}/workflow_next_question/{session_id}"))
    print(f"  Answered {i} questions.")


def phase_freeze_spec(session_id: str):
    print("\n[Phase 2/5] Freeze spec")
    result = unwrap(requests.post(f"{BASE_URL}/workflow_freeze_spec/{session_id}"))
    print(f"  Signal: {result['signal']}")


def phase_architecture(session_id: str):
    print("\n[Phase 3/5] Architecture — storing proposals & injecting tasks")
    for paradigm, score in [("oop", 88.0), ("functional", 79.0), ("data", 73.0)]:
        unwrap(requests.post(
            f"{BASE_URL}/workflow_store_proposal/{session_id}",
            params={"paradigm": paradigm, "content": f"# {paradigm.upper()} design", "score": score},
        ))

    # Start an async background job to simulate bisset-architect
    job_result = unwrap(requests.post(
        f"{BASE_URL}/workflow_start_agent/{session_id}",
        params={"agent_name": "bisset-architect"},
    ))
    job_id = job_result["job_id"]
    print(f"  Background job started: {job_id}")
    # In a real system we would poll here; for demo we inject tasks directly
    print("  (skipping real agent; injecting demo tasks directly)")

    for title, desc in [
        ("Auth service", "GitHub OAuth2 login flow"),
        ("Project CRUD", "REST endpoints for project management"),
        ("Task endpoints", "Nested task CRUD under projects"),
    ]:
        unwrap(requests.post(
            f"{BASE_URL}/workflow_add_task/{session_id}",
            params={"title": title, "description": desc},
        ))
    print("  Injected 3 tasks.")


def phase_implement(session_id: str):
    print("\n[Phase 4/5] Implementation")
    done = 0
    while True:
        result = unwrap(requests.get(f"{BASE_URL}/workflow_next_task/{session_id}"))
        if result.get("signal") == "all_tasks_complete":
            break
        task_id = result["id"]
        print(f"  Implementing: {result['title']} (model: {result.get('recommended_model', '?')})")
        # Record a passing test run
        run = unwrap(requests.post(
            f"{BASE_URL}/workflow_run_tests/{session_id}",
            params={"task_id": task_id, "passed": 8, "failed": 0, "coverage_pct": 85.0},
        ))
        assert run["ok"]
        # Complete the task
        unwrap(requests.post(f"{BASE_URL}/workflow_complete_task/{session_id}/{task_id}"))
        done += 1
    print(f"  Completed {done} tasks.")


def phase_report(session_id: str):
    print("\n[Phase 5/5] Final status")
    status = unwrap(requests.get(f"{BASE_URL}/workflow_status/{session_id}"))
    print(f"  Phase          : {status['phase']}")
    print(f"  Background jobs: {len(status.get('background_jobs', []))}")
    events = unwrap(requests.get(f"{BASE_URL}/workflow_get_events/{session_id}"))
    print(f"  Events logged  : {len(events.get('events', []))}")


# ─── Main ─────────────────────────────────────────────────────────────────────

def main():
    print("=== Bisset Autonomous Loop ===")
    # Verify server is up
    health = requests.get(f"{BASE_URL}/health").json()
    if health.get("status") != "healthy":
        print("ERROR: Workflow server is not healthy.", file=sys.stderr)
        sys.exit(1)

    # Create session with async_mode enabled
    session = unwrap(requests.post(
        f"{BASE_URL}/workflow_new_session",
        params={"project_name": "autonomous-demo", "mcp_client": "claude-mcp", "async_mode": True},
    ))
    session_id = session["id"]
    print(f"Session created: {session_id}")

    phase_interview(session_id)
    phase_freeze_spec(session_id)
    phase_architecture(session_id)
    phase_implement(session_id)
    phase_report(session_id)

    print(f"\n✓ Autonomous loop complete for session {session_id}")


if __name__ == "__main__":
    main()
