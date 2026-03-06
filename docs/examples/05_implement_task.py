"""
Example 05: Implement a single task
=====================================
Retrieves the next pending task, inspects the model recommendation, records
a simulated test run, and marks the task complete.

In a real workflow the "implementation" step is performed by a Claude sub-agent
(e.g. bisset-backend). This example shows the HTTP interactions that wrap it.

Run:
    python docs/examples/05_implement_task.py <session_id>
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


def simulate_implementation(task: dict) -> dict:
    """
    Placeholder for the actual Claude sub-agent call.

    In production this would:
      1. Select the right specialist (bisset-backend, bisset-frontend, etc.)
      2. Pass the task description + acceptance_criteria as context
      3. Wait for the agent to write code and tests
      4. Run pytest and collect results

    Returns simulated test results.
    """
    print(f"  [simulate] Implementing: {task['title']}")
    print(f"  [simulate] Recommended model: {task.get('recommended_model', 'unknown')}")
    print(f"  [simulate] Complexity score : {task.get('complexity_score', 0):.1f}")
    return {
        "passed": 12,
        "failed": 0,
        "coverage_pct": 91.3,
        "runner_output": "12 passed in 1.23s",
    }


def main(session_id: str):
    print(f"Implementation phase for session: {session_id}\n{'─' * 45}")

    tasks_implemented = 0

    while True:
        # ── Get next task ─────────────────────────────────────────────────────
        result = unwrap(requests.get(f"{BASE_URL}/workflow_next_task/{session_id}"))

        if result.get("signal") == "all_tasks_complete":
            print(f"\n✓ All tasks complete ({tasks_implemented} implemented this run).")
            break

        task_id = result["id"]
        print(f"\nTask [{task_id}]: {result['title']}")
        print(f"  Description : {result.get('description', '')[:80]}")
        print(f"  Criteria    : {result.get('acceptance_criteria', '')[:80]}")

        # ── Simulate implementation ───────────────────────────────────────────
        test_results = simulate_implementation(result)

        # ── Record test run ───────────────────────────────────────────────────
        run = unwrap(
            requests.post(
                f"{BASE_URL}/workflow_run_tests/{session_id}",
                params={
                    "task_id": task_id,
                    "passed": test_results["passed"],
                    "failed": test_results["failed"],
                    "coverage_pct": test_results["coverage_pct"],
                    "runner_output": test_results["runner_output"],
                },
            )
        )
        ok_icon = "✓" if run["ok"] else "✗"
        print(f"  Tests {ok_icon}   : {run['passed']} passed, {run['failed']} failed  "
              f"coverage={run['coverage_pct']:.1f}%")

        if not run["ok"]:
            print("  ✗ Tests failed — task not marked complete.")
            continue

        # ── Mark task complete ────────────────────────────────────────────────
        completion = unwrap(
            requests.post(
                f"{BASE_URL}/workflow_complete_task/{session_id}/{task_id}",
                params={"test_results": json.dumps(test_results)},
            )
        )
        print(f"  Status      : {completion['status']}")
        tasks_implemented += 1

    # ── Final workflow status ─────────────────────────────────────────────────
    status = unwrap(requests.get(f"{BASE_URL}/workflow_status/{session_id}"))
    print(f"\nWorkflow phase : {status['phase']}")
    print(f"Background jobs: {len(status.get('background_jobs', []))}")

    return session_id


if __name__ == "__main__":
    if len(sys.argv) < 2:
        print("Usage: python 05_implement_task.py <session_id>", file=sys.stderr)
        sys.exit(1)

    main(sys.argv[1])
    print(f"\nNext step: python docs/examples/06_autonomous_loop.py {sys.argv[1]}")
