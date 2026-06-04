"""Bisset v2 Workflow Engine — orchestration with rule evaluation and gate logic."""
import hashlib
import json
import os
import re
import subprocess
from typing import Optional

from .storage import Storage
from .rules import RuleEngine, Action
from .adapters import get_adapter, AdapterResult, strip_ansi
from .gherkin import derive_filename, sanitize_filename, check_syntax

# Sane defaults applied when neither the step nor the session define rules.
# Coverage is intentionally absent: only the behave adapter reports a real
# scenario coverage; the pytest/generic adapters always report 0.0.
DEFAULT_RULES = [
    {"when": "no_tests", "then": "ask_user"},
    {"when": "tests_pass AND gate == 'tests_only'", "then": "advance"},
    {"when": "tests_pass", "then": "ask_user"},  # human_approval / tests+human
    {"when": "tests_fail AND retries < 3", "then": "retry"},
    {"when": "always", "then": "ask_user"},
]


class WorkflowEngine:
    """Core workflow engine integrating storage, rules, and test adapters."""

    def __init__(self, db: Storage):
        self.db = db

    # -- Project ----------------------------------------------------------------

    def create_project(self, name: str, path: str, **config) -> str:
        """Create a project and lock it."""
        pid = self.db.create_project(
            name=name,
            path=path,
            test_runner=config.get("test_runner", "generic"),
            test_args=config.get("test_args", ""),
            adapter=config.get("adapter", "generic"),
            features_dir=config.get("features_dir", "features/"),
        )
        self.db.lock_project(pid)
        return pid

    def detect_project(self, cwd: str) -> dict | None:
        """Detect project by matching cwd to stored path."""
        return self.db.get_project_by_path(cwd)

    # -- Session ----------------------------------------------------------------

    def start_session(self, project_id: str, workflow_type: str,
                      default_rules: list[dict] | None = None) -> str:
        """Start a new session for a project."""
        self.db.lock_project(project_id)
        sid = self.db.create_session(workflow_type, default_rules=default_rules)
        self.db.add_event(sid, "session_started", data={
            "workflow_type": workflow_type,
            "project_id": project_id,
        })
        return sid

    def resume_session(self, project_id: str) -> str:
        """Resume the most recent pausable session for a project."""
        self.db.lock_project(project_id)
        sessions = self.db.list_sessions(project_id=project_id)
        # Find most recent non-completed session
        for sess in reversed(sessions):
            if sess["status"] in ("active", "paused"):
                self.db.update_session_status(sess["id"], "active")
                self.db.add_event(sess["id"], "session_resumed")
                return sess["id"]
        raise RuntimeError(f"No resumable session found for project {project_id}")

    def session_status(self, session_id: str) -> dict:
        """Get comprehensive session status."""
        session = self.db.get_session(session_id)
        steps = self.db.list_steps(session_id)
        current = self.db.get_current_step(session_id)
        return {
            "session": session,
            "steps": steps,
            "current_step": current,
            "total_steps": len(steps),
            "completed_steps": sum(1 for s in steps if s["status"] == "passed"),
            "failed_steps": sum(1 for s in steps if s["status"] == "failed"),
        }

    # -- Step -------------------------------------------------------------------

    def add_step(self, session_id: str, title: str, description: str, order: int,
                 **kwargs) -> str:
        """Add a step to a session."""
        step_id = self.db.add_step(session_id, title, description, order, **kwargs)
        self.db.add_event(session_id, "step_added", step_id=step_id, data={
            "title": title, "order": order,
        })
        return step_id

    def current_step(self, session_id: str) -> dict | None:
        """Get the current active or next pending step."""
        return self.db.get_current_step(session_id)

    # -- Gherkin ------------------------------------------------------------------

    def _feature_paths(self, step: dict, project: dict) -> tuple[str, str]:
        """Return (rel_path, abs_path) for a step's feature file."""
        rel = step["feature_path"]
        return rel, os.path.join(project["path"], rel)

    def set_feature(self, step_id: str, session_id: str, content: str,
                    filename: str | None = None) -> dict:
        """Validate, write to disk (disk = truth) and register content + hash."""
        step = self.db.get_step(step_id)
        if not step:
            raise ValueError(f"Step not found: {step_id}")
        errors = check_syntax(content)
        if errors:
            return {"written": False, "errors": errors}

        session = self.db.get_session(session_id)
        if not session:
            raise ValueError(f"Session not found: {session_id}")
        project = self.db.get_project(session["project_id"])
        if not project:
            raise ValueError(f"Project not found: {session['project_id']}")
        name = sanitize_filename(filename) if filename else derive_filename(step["title"])
        features_dir = project.get("features_dir", "features/").strip("/") or "features"
        rel_path = f"{features_dir}/{name}"
        abs_path = os.path.join(project["path"], rel_path)

        os.makedirs(os.path.dirname(abs_path), exist_ok=True)
        with open(abs_path, "w", encoding="utf-8") as fh:
            fh.write(content)

        digest = hashlib.sha256(content.encode("utf-8")).hexdigest()
        self.db.update_step(step_id, feature_path=rel_path,
                            feature_content=content, feature_hash=digest)
        self.db.add_event(session_id, "feature_set", step_id=step_id,
                          data={"feature_path": rel_path, "hash": digest})
        return {"written": True, "feature_path": rel_path,
                "hash": digest, "errors": []}

    def _detect_drift(self, step: dict, session_id: str, abs_path: str) -> tuple[str, bool]:
        """Read disk content and realign the DB copy if it drifted.

        Returns (disk_content, drifted). Caller must ensure the file exists.
        """
        try:
            with open(abs_path, "r", encoding="utf-8") as fh:
                disk_content = fh.read()
        except UnicodeDecodeError as exc:
            raise ValueError(f"Feature file is not valid UTF-8: {abs_path}") from exc
        disk_hash = hashlib.sha256(disk_content.encode("utf-8")).hexdigest()
        drifted = bool(step.get("feature_hash")) and disk_hash != step["feature_hash"]
        if drifted:
            self.db.update_step(step["id"], feature_content=disk_content,
                                feature_hash=disk_hash)
            self.db.add_event(session_id, "feature_drift", step_id=step["id"],
                              data={"feature_path": step["feature_path"],
                                    "new_hash": disk_hash})
        return disk_content, drifted

    def get_feature(self, step_id: str, session_id: str) -> dict:
        """Read the step's feature from disk (truth), reporting drift/missing."""
        step = self.db.get_step(step_id)
        if not step:
            raise ValueError(f"Step not found: {step_id}")
        if not step.get("feature_path"):
            raise ValueError(f"Step has no feature_path: {step_id}")
        session = self.db.get_session(session_id)
        if not session:
            raise ValueError(f"Session not found: {session_id}")
        project = self.db.get_project(session["project_id"])
        if not project:
            raise ValueError(f"Project not found: {session['project_id']}")
        rel_path, abs_path = self._feature_paths(step, project)

        if not os.path.isfile(abs_path):
            return {"content": step.get("feature_content"),
                    "feature_path": rel_path,
                    "feature_drifted": False, "file_missing": True}

        content, drifted = self._detect_drift(step, session_id, abs_path)
        return {"content": content, "feature_path": rel_path,
                "feature_drifted": drifted, "file_missing": False}

    # -- Gherkin Validation -----------------------------------------------------

    _UNDEFINED_COUNT_RE = re.compile(r"(\d+)\s+undefined")
    _SNIPPET_STEP_RE = re.compile(r"@(?:given|when|then|step)\(u?['\"](.+?)['\"]\)")

    def validate_feature(self, step_id: str, session_id: str) -> dict:
        """Dry-run validation: syntax + step definitions, without executing.

        Verified against behave 1.3.3: snippets corrupt --format json output,
        so the JSON pass runs with --no-snippets and exact undefined step
        names come from a second plain dry-run's snippet block.
        """
        step = self.db.get_step(step_id)
        if not step:
            raise ValueError(f"Step not found: {step_id}")
        if not step.get("feature_path"):
            raise ValueError(f"Step has no feature_path: {step_id}")
        session = self.db.get_session(session_id)
        if not session:
            raise ValueError(f"Session not found: {session_id}")
        project = self.db.get_project(session["project_id"])
        if not project:
            raise ValueError(f"Project not found: {session['project_id']}")
        if project.get("adapter") != "behave":
            raise ValueError("step_validate_feature requires the behave adapter")

        runner = project["test_runner"]
        cmd = [runner, "--dry-run", "--no-snippets", "--format", "json",
               step["feature_path"]]
        try:
            proc = subprocess.run(cmd, capture_output=True, text=True,
                                  timeout=60, cwd=project["path"])
        except FileNotFoundError:
            raise ValueError(f"behave runner not found: {runner}")

        output = strip_ansi(proc.stdout + proc.stderr)

        try:
            start = proc.stdout.index('[')
            end = proc.stdout.rindex(']')
            json.loads(proc.stdout[start:end + 1])
        except (ValueError, json.JSONDecodeError):
            return {"syntax_ok": False, "steps_defined": False,
                    "undefined_steps": [], "errors": [output]}

        m = self._UNDEFINED_COUNT_RE.search(output)
        undefined_count = int(m.group(1)) if m else 0
        undefined_steps: list[str] = []
        if undefined_count:
            proc2 = subprocess.run([runner, "--dry-run", step["feature_path"]],
                                   capture_output=True, text=True,
                                   timeout=60, cwd=project["path"])
            snippet_out = strip_ansi(proc2.stdout + proc2.stderr)
            undefined_steps = list(dict.fromkeys(
                self._SNIPPET_STEP_RE.findall(snippet_out)))

        return {"syntax_ok": True,
                "steps_defined": undefined_count == 0,
                "undefined_steps": undefined_steps,
                "errors": []}

    # -- Test Execution ---------------------------------------------------------

    def record_test_run(self, step_id: str, session_id: str,
                        passed: int, failed: int, coverage: float,
                        runner_output: str = "") -> str:
        """Record a test run result."""
        run_id = self.db.add_test_run(step_id, session_id, passed, failed, coverage, runner_output)
        self.db.update_step(step_id, current_coverage=coverage)
        return run_id

    def run_tests(self, step_id: str, session_id: str) -> tuple[AdapterResult, bool]:
        """Execute tests for a step via subprocess.

        Returns (result, feature_drifted). Disk is truth: a drifted feature
        still runs, but the drift is recorded and reported.
        """
        step = self.db.get_step(step_id)
        if not step or not step.get("feature_path"):
            return AdapterResult(passed=0, failed=0), False

        session = self.db.get_session(session_id)
        project = self.db.get_project(session["project_id"])

        drifted = False
        _, abs_path = self._feature_paths(step, project)
        if os.path.isfile(abs_path) and step.get("feature_hash"):
            _, drifted = self._detect_drift(step, session_id, abs_path)

        adapter = get_adapter(project.get("adapter", "generic"))
        cmd = [project["test_runner"]]
        if project.get("test_args"):
            cmd.extend(project["test_args"].split())
        cmd.append(step["feature_path"])

        try:
            proc = subprocess.run(cmd, capture_output=True, text=True, timeout=300,
                                  cwd=project["path"])
            result = adapter.parse(proc.returncode, proc.stdout, proc.stderr)
        except (subprocess.TimeoutExpired, FileNotFoundError) as e:
            result = AdapterResult(passed=0, failed=1, errors=[str(e)])

        self.record_test_run(step_id, session_id, result.passed, result.failed,
                             result.coverage, result.raw_output)
        return result, drifted

    # -- Step Completion --------------------------------------------------------

    def complete_step(self, step_id: str, session_id: str) -> str:
        """Attempt to complete a step by evaluating rules.

        Returns action string: advance, retry, ask_user, abort, skip.
        """
        step = self.db.get_step(step_id)
        session = self.db.get_session(session_id)
        latest_run = self.db.get_latest_test_run(step_id)

        # Build rule context
        has_tests = latest_run is not None
        context = {
            "tests_pass": has_tests and latest_run["failed"] == 0 and latest_run["passed"] > 0,
            "tests_fail": has_tests and latest_run["failed"] > 0,
            "coverage": latest_run["coverage"] if has_tests else 0.0,
            "retries": step["retries"],
            "gate": step.get("gate", "tests_only"),
            "no_tests": not has_tests,
        }

        # Get rules: step override, session default, or engine defaults
        rules = step.get("rules_override") or session.get("default_rules")
        if not rules:
            rules = DEFAULT_RULES

        engine = RuleEngine(rules)
        action = engine.evaluate(**context)

        # Apply action
        if action == Action.ADVANCE:
            self.db.update_step(step_id, status="passed")
            self.db.add_event(session_id, "step_completed", step_id=step_id,
                              data={"action": "advance"})
        elif action == Action.RETRY:
            self.db.update_step(step_id, status="active", retries=step["retries"] + 1)
            self.db.add_event(session_id, "step_retry", step_id=step_id,
                              data={"retries": step["retries"] + 1})
        elif action == Action.ASK_USER:
            self.db.add_event(session_id, "step_ask_user", step_id=step_id)
        elif action == Action.ABORT:
            self.db.update_step(step_id, status="failed")
            self.db.add_event(session_id, "step_aborted", step_id=step_id)
        elif action == Action.SKIP:
            self.db.update_step(step_id, status="skipped")
            self.db.add_event(session_id, "step_skipped", step_id=step_id)

        # Check if all steps done -> complete session
        steps = self.db.list_steps(session_id)
        if all(s["status"] in ("passed", "skipped") for s in steps):
            self.db.update_session_status(session_id, "completed")

        return action.value

    def skip_step(self, step_id: str, session_id: str, reason: str) -> None:
        """Skip a step with a reason."""
        self.db.update_step(step_id, status="skipped")
        self.db.add_event(session_id, "step_skipped", step_id=step_id,
                          data={"reason": reason})
