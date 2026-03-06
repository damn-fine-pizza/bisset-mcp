"""
Example 01: Start a new workflow session
========================================
Demonstrates how to create a session, inspect its metadata, and list all
existing sessions. This is always the first step in a Bisset workflow.

Run:
    python docs/examples/01_start_session.py
"""

import json
import sys
import requests

BASE_URL = "http://localhost:8765"


def unwrap(response: requests.Response) -> dict:
    """Unpack a Claude SDK TextContent wrapper and return the payload dict."""
    response.raise_for_status()
    body = response.json()
    if body.get("is_error"):
        error_text = body["content"][0]["text"]
        error_data = json.loads(error_text)
        print(f"[ERROR] {error_data.get('error')} ({error_data.get('code')})", file=sys.stderr)
        sys.exit(1)
    return json.loads(body["content"][0]["text"])


def main():
    # ── 1. Health check ───────────────────────────────────────────────────────
    health = requests.get(f"{BASE_URL}/health").json()
    print(f"Server status : {health['status']}  (v{health['version']})")

    # ── 2. Create a session ───────────────────────────────────────────────────
    session = unwrap(
        requests.post(
            f"{BASE_URL}/workflow_new_session",
            params={
                "project_name": "task-manager-app",
                "mcp_client": "claude-mcp",
                "async_mode": False,
            },
        )
    )
    session_id = session["id"]
    print(f"\nCreated session : {session_id}")
    print(f"  project_name  : {session['name']}")
    print(f"  phase         : {session['phase']}")
    print(f"  mcp_client    : {session['mcp_client']}")

    # ── 3. List all sessions ──────────────────────────────────────────────────
    listing = unwrap(requests.get(f"{BASE_URL}/workflow_list_sessions"))
    sessions = listing["sessions"]
    print(f"\nAll sessions ({len(sessions)} total):")
    for s in sessions:
        frozen = "✓" if s.get("spec_frozen_at") else "✗"
        print(f"  {s['id']}  phase={s['phase']:15s}  spec_frozen={frozen}  name={s['name']}")

    # ── 4. Retrieve the session by ID ─────────────────────────────────────────
    fetched = unwrap(requests.get(f"{BASE_URL}/workflow_get_session/{session_id}"))
    assert fetched["id"] == session_id, "Session ID mismatch!"
    print(f"\nFetched session {session_id} — OK")

    return session_id


if __name__ == "__main__":
    sid = main()
    print(f"\nNext step: python docs/examples/02_interview.py {sid}")
