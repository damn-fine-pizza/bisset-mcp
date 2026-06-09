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
            "interview": self._interview_block(session_id, session) if session else None,
            "analysis": self._analysis_block(session_id, session) if session else None,
        }

    # -- Interview ----------------------------------------------------------------

    def interview_question(self, session_id: str, question: str) -> dict:
        """Register an interview question (one open at a time; reopens if complete)."""
        question = (question or "").strip()
        if not question:
            raise ValueError("Question must not be empty")
        session = self.db.get_session(session_id)
        if not session:
            raise ValueError(f"Session not found: {session_id}")
        open_q = self.db.get_open_interview_question(session_id)
        if open_q:
            raise ValueError(
                f"An interview question is already open: {open_q['question']!r} "
                f"(order {open_q['order']}). Record its answer via "
                "interview_answer before asking another."
            )
        reopened = session.get("interview_status") == "complete"
        qid = self.db.add_interview_question(session_id, question)
        if reopened:
            self.db.add_event(session_id, "interview_reopened",
                              data={"question_id": qid})
        q = self.db.get_interview_question(qid)
        self.db.add_event(session_id, "question_asked",
                          data={"question_id": qid, "order": q["order"],
                                "question": question})
        return {"question_id": qid, "order": q["order"], "reopened": reopened}

    def interview_answer(self, question_id: str, answer: str) -> dict:
        """Record (or revise) the answer to an interview question.

        Revising never changes interview_status: only interview_question
        reopens a completed interview.
        """
        answer = (answer or "").strip()
        if not answer:
            raise ValueError("Answer must not be empty")
        q = self.db.get_interview_question(question_id)
        if not q:
            raise ValueError(f"Interview question not found: {question_id}")
        revised = q["status"] == "answered"
        self.db.answer_interview_question(question_id, answer)
        # Deliberate asymmetry with question_asked: the answer text lives on
        # the interview_questions row (canonical); events carry correlation
        # ids only, so free text is not duplicated into the audit log.
        self.db.add_event(q["session_id"],
                          "answer_revised" if revised else "answer_recorded",
                          data={"question_id": question_id, "order": q["order"]})
        return {"question_id": question_id, "order": q["order"],
                "revised": revised}

    def interview_complete(self, session_id: str) -> dict:
        """Declare the interview complete after invariant checks (gate opener)."""
        session = self.db.get_session(session_id)
        if not session:
            raise ValueError(f"Session not found: {session_id}")
        if session.get("interview_status") is None:
            raise ValueError("No interview was started for this session.")
        if session.get("interview_status") == "complete":
            # Idempotent: an MCP client may retry — don't duplicate the event.
            questions = self.db.list_interview_questions(session_id)
            answered = sum(1 for q in questions if q["status"] == "answered")
            return {"interview_status": "complete",
                    "asked": len(questions), "answered": answered}
        open_q = self.db.get_open_interview_question(session_id)
        if open_q:
            raise ValueError(
                f"Cannot complete the interview: question {open_q['order']} "
                f"is still open: {open_q['question']!r}. Record its answer "
                "via interview_answer first."
            )
        questions = self.db.list_interview_questions(session_id)
        answered = sum(1 for q in questions if q["status"] == "answered")
        if answered == 0:
            raise ValueError(
                "Cannot complete the interview: no answers recorded. Ask at "
                "least one question via interview_question and record its "
                "answer."
            )
        self.db.set_interview_status(session_id, "complete")
        self.db.add_event(session_id, "interview_completed",
                          data={"asked": len(questions), "answered": answered})
        return {"interview_status": "complete",
                "asked": len(questions), "answered": answered}

    def _interview_block(self, session_id: str, session: dict) -> dict | None:
        """Interview summary for status responses (None = never started)."""
        status = session.get("interview_status")
        if status is None:
            return None
        questions = self.db.list_interview_questions(session_id)
        open_q = next((q for q in questions if q["status"] == "open"), None)
        pending = None
        if open_q:
            pending = {"id": open_q["id"], "order": open_q["order"],
                       "question": open_q["question"]}
        return {"status": status,
                "asked": len(questions),
                "answered": sum(1 for q in questions if q["status"] == "answered"),
                "pending_question": pending}

    # -- Analysis -----------------------------------------------------------------

    def analysis_submit(self, session_id: str, steps: list[dict]) -> dict:
        """Open (or replace) the analysis proposal for a session.

        Gherkin drafts are validated here so analysis_approve can never fail
        on syntax. Re-submitting an open proposal replaces it (audited as
        analysis_revised); re-submitting a terminal one opens a fresh
        proposal and re-arms the step_add gate.
        """
        session = self.db.get_session(session_id)
        if not session:
            raise ValueError(f"Session not found: {session_id}")
        if not isinstance(steps, list) or not steps:
            raise ValueError(
                "Proposal must contain at least one step "
                "({title, description?, feature_draft?})."
            )
        cleaned = []
        errors = []
        for idx, step in enumerate(steps, start=1):
            title = (step.get("title") or "").strip()
            if not title:
                raise ValueError(f"Proposal step {idx} has an empty title.")
            draft = step.get("feature_draft")
            if draft is not None:
                draft_errors = check_syntax(draft)
                if draft_errors:
                    errors.append({"order": idx, "title": title,
                                   "errors": draft_errors})
            cleaned.append({"title": title,
                            "description": (step.get("description") or "").strip(),
                            "feature_draft": draft})
        if errors:
            return {"submitted": False, "errors": errors}

        previous = session.get("analysis_status")
        self.db.replace_proposal_steps(session_id, cleaned)
        self.db.set_analysis_status(session_id, "open")
        drafted = sum(1 for s in cleaned if s["feature_draft"])
        event = "analysis_revised" if previous == "open" else "analysis_submitted"
        data = {"steps_proposed": len(cleaned), "features_drafted": drafted}
        if previous and previous != "open":
            data["previous_status"] = previous
        self.db.add_event(session_id, event, data=data)
        return {"submitted": True, "analysis_status": "open",
                "steps_proposed": len(cleaned), "features_drafted": drafted,
                "revised": previous == "open"}

    def analysis_view(self, session_id: str) -> dict:
        """Read the persisted proposal (status + proposed steps with drafts)."""
        session = self.db.get_session(session_id)
        if not session:
            raise ValueError(f"Session not found: {session_id}")
        status = session.get("analysis_status")
        if status is None:
            return {"analysis_status": None, "steps": []}
        steps = self.db.list_proposal_steps(session_id)
        return {"analysis_status": status,
                "steps": [{"order": s["order"], "title": s["title"],
                           "description": s["description"],
                           "feature_draft": s["feature_draft"]}
                          for s in steps]}

    def analysis_approve(self, session_id: str) -> dict:
        """Materialize the open proposal into real steps (+ features on disk).

        Non-atomic by declared design (see the design doc): the loop is
        ordered so a partial failure leaves a consistent prefix of real
        steps and the proposal still open.
        """
        session = self.db.get_session(session_id)
        if not session:
            raise ValueError(f"Session not found: {session_id}")
        status = session.get("analysis_status")
        if status != "open":
            raise ValueError(
                f"No open analysis proposal (status: {status}). Submit one "
                "via analysis_submit before approving."
            )
        if session.get("interview_status") == "open":
            raise ValueError(
                "Interview in progress: complete it via interview_complete "
                "before approving the analysis proposal."
            )
        proposal = self.db.list_proposal_steps(session_id)
        existing = self.db.list_steps(session_id)
        next_order = max((s["order"] for s in existing), default=0) + 1
        created = []
        features_written = 0
        # On partial failure the clean recovery is discard + fresh submit:
        # re-approving would duplicate the already-materialized prefix.
        for offset, p in enumerate(proposal):
            order = next_order + offset
            # storage-level add: the engine gate guards the manual tool
            # path, not this internal promotion
            step_id = self.db.add_step(session_id, p["title"],
                                       p["description"], order)
            self.db.add_event(session_id, "step_added", step_id=step_id,
                              data={"title": p["title"], "order": order,
                                    "source": "analysis"})
            feature_path = None
            if p["feature_draft"]:
                # batch write: titles may slugify identically — prefixing
                # with the materialized step order guarantees one file per
                # step, across re-approvals too
                result = self.set_feature(
                    step_id, session_id, p["feature_draft"],
                    filename=f"{order:02d}-{derive_filename(p['title'])}")
                if not result["written"]:
                    # unreachable: drafts are validated at submit time
                    raise ValueError(
                        f"Feature draft for proposal step {p['order']} failed "
                        f"validation at approve time: {result['errors']}"
                    )
                feature_path = result["feature_path"]
                features_written += 1
            created.append({"proposal_order": p["order"], "step_id": step_id,
                            "order": order, "feature_path": feature_path})
        self.db.set_analysis_status(session_id, "approved")
        self.db.add_event(session_id, "analysis_approved",
                          data={"steps_created": len(created),
                                "features_written": features_written})
        return {"analysis_status": "approved", "steps": created,
                "steps_created": len(created),
                "features_written": features_written}

    def analysis_discard(self, session_id: str) -> dict:
        """Discard the open proposal; rows remain readable via analysis_view."""
        session = self.db.get_session(session_id)
        if not session:
            raise ValueError(f"Session not found: {session_id}")
        status = session.get("analysis_status")
        if status != "open":
            raise ValueError(
                f"No open analysis proposal to discard (status: {status})."
            )
        steps = self.db.list_proposal_steps(session_id)
        self.db.set_analysis_status(session_id, "discarded")
        self.db.add_event(session_id, "analysis_discarded",
                          data={"steps_discarded": len(steps)})
        return {"analysis_status": "discarded", "steps_discarded": len(steps)}

    def _analysis_block(self, session_id: str, session: dict) -> dict | None:
        """Analysis summary for status responses (None = never started)."""
        status = session.get("analysis_status")
        if status is None:
            return None
        steps = self.db.list_proposal_steps(session_id)
        return {"status": status,
                "steps_proposed": len(steps),
                "features_drafted": sum(1 for s in steps if s["feature_draft"]),
                "steps": [{"order": s["order"], "title": s["title"],
                           "has_draft": bool(s["feature_draft"])}
                          for s in steps]}

    # -- Step -------------------------------------------------------------------

    def add_step(self, session_id: str, title: str, description: str, order: int,
                 **kwargs) -> str:
        """Add a step to a session (gated while an interview or an analysis
        proposal is open; check order: interview first, then analysis)."""
        session = self.db.get_session(session_id)
        if session and session.get("interview_status") == "open":
            open_q = self.db.get_open_interview_question(session_id)
            if open_q:
                raise ValueError(
                    f"Interview in progress: question {open_q['order']} is open "
                    f"({open_q['question']!r}). Answer it with interview_answer, "
                    "then call interview_complete."
                )
            raise ValueError(
                "Interview in progress: all questions are answered but the "
                "interview is not declared complete. Call interview_complete "
                "to add steps."
            )
        if session and session.get("analysis_status") == "open":
            n = len(self.db.list_proposal_steps(session_id))
            raise ValueError(
                f"Analysis proposal pending: an open proposal with {n} "
                "step(s) exists. Approve it with analysis_approve or discard "
                "it with analysis_discard before adding steps manually."
            )
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
        # behave refuses to run a features dir without a steps/ package;
        # prepare it empty so validate/run give honest verdicts (issue #6)
        os.makedirs(os.path.join(os.path.dirname(abs_path), "steps"), exist_ok=True)
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
            # A ConfigError (e.g. missing steps/ directory) is an environment
            # problem, not a Gherkin verdict — never report it as syntax_ok
            # False (issue #6).
            if "ConfigError" in output:
                detail = next((ln for ln in output.splitlines()
                               if "ConfigError" in ln), output.strip())
                raise ValueError(f"behave configuration error: {detail}")
            return {"syntax_ok": False, "steps_defined": False,
                    "undefined_steps": [], "errors": [output]}

        matches = self._UNDEFINED_COUNT_RE.findall(output)
        undefined_count = int(matches[-1]) if matches else 0
        undefined_steps: list[str] = []
        if undefined_count:
            try:
                proc2 = subprocess.run([runner, "--dry-run", step["feature_path"]],
                                       capture_output=True, text=True,
                                       timeout=60, cwd=project["path"])
                snippet_out = strip_ansi(proc2.stdout + proc2.stderr)
                undefined_steps = list(dict.fromkeys(
                    self._SNIPPET_STEP_RE.findall(snippet_out)))
            except (subprocess.TimeoutExpired, FileNotFoundError):
                undefined_steps = []  # count is still reported; names are best-effort

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
