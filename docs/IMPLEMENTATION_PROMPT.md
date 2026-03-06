# Claude MCP Server Implementation Prompt

## Context & Objective

You are tasked with implementing a **Claude-compatible MCP server** based on the Bisset workflow orchestration system. Bisset is a two-tier architecture for BDD-first software development:

- **Frontend:** STDIO MCP proxy (currently FastMCP for Copilot CLI)
- **Backend:** FastAPI HTTP server with SQLite persistence

Your job is to adapt this system for **Claude** while preserving all core features:
- Multi-phase BDD workflow (interview → spec freeze → architecture → Gherkin → implementation → coverage gate)
- Sub-agent system for specialized tasks (backend, frontend, database, cloud, DevOps, embedded, UX, docs)
- Autonomous execution mode
- Test enforcement (80% BDD coverage threshold)
- Architecture evaluation (OOP, Functional, Data-Oriented paradigms)

**Timeline:** This is a **specification-driven implementation**—a detailed plan exists in `/plan.md`. You must follow that plan as the contract.

---

## Phase A: Foundation (Critical Path)

### Task A1: Update SQLite Schema to v7
**File:** `orchestrator/workflow_server/storage.py`

**Requirements:**
1. Increment SCHEMA_VERSION from 6 to 7
2. Add migration for schema v7 in `_migrate()` method:
   - `sessions.mcp_client` (TEXT, enum: 'copilot-cli' | 'claude-mcp' | 'generic')
   - `sessions.phase` (TEXT, tracks current workflow phase)
   - `sessions.sub_phase` (TEXT, tracks sub-phase state)
   - `sessions.spec_frozen_at` (REAL, timestamp)
   - `questions.order_index` (INTEGER, reproducible interview order)
   - `tasks.assigned_model` (TEXT, enum: 'haiku' | 'sonnet' | 'opus')
   - NEW table: `proposals(id, session_id, paradigm, content, score, created_at)`
   - NEW table: `artifacts(id, task_id, session_id, file_path, change_type, diff, created_at)`
3. Ensure backward compatibility: existing v6 databases migrate automatically
4. Run migration tests against sample database

**Success Criteria:**
- Schema migration is idempotent (safe to run multiple times)
- All new columns exist in v7 database
- Old databases (v6) auto-migrate with no data loss
- `pytest` tests pass for storage layer

---

### Task A2: Port MCP Server to Claude SDK
**File:** `orchestrator/mcp_server/server.py` (rewrite from FastMCP to Claude SDK)

**Requirements:**
1. Replace FastMCP library with `anthropic` package (official Claude SDK)
2. Implement MCP protocol compatibility:
   - Tool registration: All 20+ tools (see plan.md section 3.3)
   - Prompt registration: 7 phase-specific system prompts
   - Result wrapper: Return `ToolResult` with `TextContent` for Claude
3. Update entry point `__main__.py` to initialize Claude SDK
4. All tool responses must include:
   ```json
   {
     "content": [
       {
         "type": "text",
         "text": "<response>"
       }
     ],
     "is_error": false
   }
   ```
5. Error responses must follow format:
   ```json
   {
     "content": [
       {
         "type": "text",
         "text": "error: error_code\nmessage: human-readable message"
       }
     ],
     "is_error": true
   }
   ```
6. Update `requirements.txt` with any new dependencies

**Success Criteria:**
- Server starts without errors: `python -m orchestrator.mcp_server`
- All tools are discoverable via MCP protocol
- Responses are Claude SDK compatible
- No FastMCP references remain in codebase

---

### Task A3: Add Model-Aware Task Routing
**File:** `orchestrator/workflow_server/engine.py`

**Requirements:**
1. Implement task complexity analysis in `next_task()` method:
   - Simple tasks (CRUD, boilerplate) → recommend 'haiku'
   - Medium tasks (business logic, integration) → recommend 'sonnet'
   - Complex tasks (architecture, refactoring, debug) → recommend 'opus'
2. Logic: Count keywords in task description
   - "CRUD", "boilerplate", "schema", "template" → simple
   - "integration", "business logic", "validation", "error handling" → medium
   - "refactor", "optimize", "debug", "architecture", "design" → complex
3. Add `recommended_model` field to task response:
   ```json
   {
     "task": {
       "id": "auth-jwt",
       "recommended_model": "sonnet",
       "override_model": null
     }
   }
   ```
4. Allow users to override via `workflow_add_task(..., assigned_model='opus')`
5. Store assignment in `tasks.assigned_model` column

**Success Criteria:**
- Task response includes `recommended_model` field
- Simple/medium/complex tasks route to correct models
- Overrides are persisted and respected
- Tests verify routing logic

---

### Task A4: Implement Claude-Optimized Response Wrappers
**File:** `orchestrator/workflow_server/app.py`

**Requirements:**
1. Create `@app.middleware` that wraps all tool responses:
   - Extract response body
   - Wrap in Claude SDK `TextContent` format
   - Add metadata: `success`, `duration_ms`
2. Add response examples to docstrings:
   ```python
   @app.post('/tools/workflow_new_session')
   def tool_new_session(req: ToolRequest):
       """
       Create a new workflow session.
       
       Response:
       {
         "content": [{"type": "text", "text": "..."}],
         "is_error": false,
         "metadata": {"duration_ms": 45}
       }
       """
   ```
3. Ensure all 20+ endpoints follow consistent wrapper format
4. Test with sample Claude SDK client

**Success Criteria:**
- All endpoints return Claude SDK compatible format
- Response time metrics are tracked
- Error responses are properly formatted
- Integration test with Claude SDK client passes

---

### Task A5: Add Prompt Caching Support
**File:** `orchestrator/workflow_server/app.py` (new endpoint), `mcp_server/prompts.py` (new)

**Requirements:**
1. Create prompts per workflow phase in `mcp_server/prompts.py`:
   - Phase 2 (Interview): Guidelines for asking good requirements questions
   - Phase 2.5 (Validation): Checklist for completeness, consistency, testability
   - Phase 3 (Architecture): Scoring framework for OOP/Functional/Data-Oriented
   - Phase 4 (Gherkin): BDD semantics rules, test coverage strategy
   - Phase 5 (Implementation): Domain routing logic, specialist selection
   - Phase 6 (Coverage Gate): Pass/fail criteria (≥80% coverage)
   - Review (Audit): Conformance check template
2. Implement auto-caching logic:
   - When spec > 10,000 characters, mark for caching
   - Add `cache_control: "ephemeral"` header to response
   - Claude SDK will handle caching automatically
3. New endpoint: `POST /prompts/phase/{phase_name}`
   - Returns cached or uncached prompt as needed
   - Includes metadata: `cached`, `token_estimate`

**Success Criteria:**
- 7 phase prompts are registered and discoverable
- Large specs are auto-marked for caching
- Prompt caching reduces token consumption on repeated queries
- Integration test verifies caching headers

---

### Task A6: Implement Async Sub-Agent Mode
**File:** `orchestrator/workflow_server/engine.py`

**Requirements:**
1. Add `async_mode: bool` parameter to `workflow_start()`:
   ```json
   {
     "project_meta": {...},
     "async_mode": true
   }
   ```
2. When `async_mode=true`:
   - Sub-agent calls return immediately with `status: 'pending'`
   - Provide polling endpoint: `GET /tools/workflow_status?session_id=X`
   - Return current task + background job status
3. When `async_mode=false` (default):
   - Maintain backward compatibility with Copilot CLI behavior
   - Blocks until sub-agent completes
4. New table: `background_jobs(id, session_id, agent_name, status, result, created_at, updated_at)`
5. Job lifecycle:
   - `created` → `running` → `completed` OR `failed`
   - Store result in JSON format

**Success Criteria:**
- Async mode flag is functional and persisted
- Background jobs are tracked in database
- Polling endpoint returns accurate status
- Tests verify job lifecycle

---

## Phase B: Documentation (Can run in parallel with Phase A)

### Task B1: API Reference Document
**File:** `docs/api-reference.md`

**Requirements:**
1. Document all 20+ HTTP endpoints with:
   - Endpoint: `POST /tools/{tool_name}`
   - Description (1-2 sentences)
   - Request schema (JSON example)
   - Response schema (JSON example)
   - Error cases (with error codes)
   - Example cURL command
2. Include sections:
   - Base URL & authentication
   - Error response format
   - Tool categories (session, interview, execution, testing, introspection, etc.)
3. For each tool, provide:
   - Session management (new_session, switch_session, list_sessions, detect_session)
   - Interview (start, next_question, record_answer, list_questions)
   - Spec freeze & architecture (freeze_spec, store_proposal, list_proposals)
   - Execution (next_task, add_task, run_tests, accept_task_result)
   - Introspection (status, report, is_done, get_events)
   - Utility (bootstrap_project, run_until_blocked, store_note, advance_phase)
4. Add troubleshooting section for common errors
5. Use JSON schema notation for clarity

**Success Criteria:**
- All 20+ tools documented
- Request/response examples are valid JSON
- Error cases are covered
- Document is readable and searchable

---

### Task B2: Architecture Diagrams Document
**File:** `docs/architecture-claude.md`

**Requirements:**
1. Create 4 Mermaid diagrams:
   - **Phase State Machine:** Shows all 6 workflow phases + review, transitions, decision points
   - **Sub-Agent Routing:** Shows bisset-implement dispatcher → 8 domain specialists
   - **Model Assignment Strategy:** Flowchart for task complexity → recommended model
   - **BDD Coverage Gate:** Flow from test execution → coverage check → accept or loop back
2. Create 4 Architecture Decision Records (ADRs):
   - **ADR-001:** Keep two-tier architecture (STDIO proxy + HTTP backend)
   - **ADR-002:** Model-aware task routing (Haiku/Sonnet/Opus per task)
   - **ADR-003:** Async mode for sub-agents (polling vs blocking)
   - **ADR-004:** Prompt caching strategy (auto-detect >10K chars)
3. Each ADR should include:
   - Title
   - Decision (what was decided)
   - Rationale (why this decision)
   - Consequences (pros/cons)
   - Alternatives (what was considered)
4. Add appendix: Schema v6 → v7 migration guide

**Success Criteria:**
- All 4 diagrams render correctly in Markdown
- All 4 ADRs follow established format
- Diagrams are clear and easy to follow
- Migration guide is complete

---

### Task B3: Implementation Guide
**File:** `docs/implementation-guide.md`

**Requirements:**
1. Section 1: Setup & Environment
   - Prerequisites (Python 3.10+, pip, virtualenv)
   - Clone & install: `pip install -r orchestrator/requirements.txt`
   - Environment variables: `DATABASE_PATH`, `WORKFLOW_SERVER_PORT`, `MCP_SERVER_HOST`
   - Start workflow_server: `python -m orchestrator.workflow_server`
   - Start mcp_server: `python -m orchestrator.mcp_server`
   - Verify health: `curl http://localhost:8765/health`

2. Section 2: Database Migration
   - How to migrate from v6 → v7
   - Backup existing database before migration
   - Run migration automatically on first v7 startup
   - Rollback procedure (keep backup)

3. Section 3: Testing Strategy
   - Unit tests (storage, engine, routes)
   - Integration tests (MCP protocol)
   - How to run: `pytest orchestrator/`
   - Coverage requirements (>80%)

4. Section 4: Debugging & Troubleshooting
   - Enable verbose logging: `WORKFLOW_PRETTY_JSON_LOGS=1`
   - Common errors & solutions:
     - "No active session" → call workflow_new_session()
     - "Test coverage too low" → implement more test cases
     - "Model not available" → check API key, model name
   - How to inspect session state: `workflow_get_events(limit=100)`
   - How to recover from crash: `workflow_detect_session(cwd=...)`

5. Section 5: Configuration
   - `.env` example file with all options
   - BDD runner configuration (pytest, behave, cucumber)
   - Features directory location
   - Coverage thresholds

**Success Criteria:**
- Setup instructions are step-by-step and copy-paste-ready
- Migration guide covers edge cases
- Testing strategy is executable
- Debugging section addresses real problems

---

### Task B4: Code Examples (Python)
**Files:** `docs/examples/01_*.py` through `docs/examples/06_*.py`

**Requirements:**
1. **Example 01: Starting a Session**
   - Import Claude SDK + HTTP client
   - Call `workflow_new_session("MyProject")`
   - Parse response
   - Output: session_id
   - ~50 lines

2. **Example 02: Recording Interview Answers**
   - Loop through `workflow_next_question()` until done
   - For each question, call `workflow_record_answer(question_id, answer_text)`
   - Show sample Q&A pairs
   - ~80 lines

3. **Example 03: Freezing Spec & Reviewing**
   - Call `workflow_freeze_spec()`
   - Retrieve and display frozen spec from filesystem
   - List all questions via `workflow_list_questions(answered=true)`
   - ~60 lines

4. **Example 04: Architecture Evaluation**
   - Call `workflow_list_proposals()` to retrieve OOP/Functional/Data-Oriented proposals
   - Parse proposal scores
   - Show traceability to requirements
   - ~70 lines

5. **Example 05: Implementing a Task**
   - Call `workflow_next_task()` to get current task
   - Implement feature based on acceptance_criteria
   - Call `workflow_run_tests(task_id)` to verify
   - Call `workflow_accept_task_result(...)` to mark done
   - Loop until all tasks done
   - ~120 lines

6. **Example 06: Autonomous Loop**
   - Call `workflow_run_until_blocked(max_iterations=20, max_minutes=30)`
   - Handle return status: 'done' | 'blocked' | 'timeout' | 'iteration_limit'
   - If blocked, show fix recommendation
   - Retry or escalate
   - ~100 lines

**Success Criteria:**
- All 6 examples are self-contained and runnable
- Examples use realistic data
- Code is well-commented
- Each example focuses on one workflow segment
- Examples can be combined to form complete workflow

---

## Phase C: Core Agents (Sequential, depends on Phase A)

### Task C1: Port bisset-interview Agent
**File:** `orchestrator/agents/bisset_interview.py` (new)

**Requirements:**
1. Implement interview loop:
   - Load question catalog from `workflow_server/catalog.py`
   - Retrieve next unanswered question
   - Present question to user (via Claude conversation)
   - Validate answer (must be non-empty, reasonable length)
   - Record answer via HTTP call to workflow_server
   - Repeat until all questions answered
2. Return success signal: `"interview_complete"` to be passed to `workflow_advance_phase()`
3. Handle edge cases:
   - User skips question (allow, mark as "skipped")
   - User provides unclear answer (ask clarification)
   - Timeout (save progress, allow resume later)
4. Track progress: Show "Question X of Y" during interview

**Success Criteria:**
- Interview can be run end-to-end
- All answers are recorded in database
- Interview can be paused and resumed
- Signal `interview_complete` can be sent to advance phase

---

### Task C2: Port bisset-requirements-validate Agent
**File:** `orchestrator/agents/bisset_requirements_validate.py` (new)

**Requirements:**
1. After interview completes, validate answers on 3 dimensions:
   - **Completeness:** All critical sections have answers (scope, features, constraints)
   - **Consistency:** Answers don't contradict each other (e.g., timeline vs scope)
   - **Testability:** Requirements include acceptance criteria and measurable outcomes
2. Scoring:
   - Each dimension: 0-100 score
   - Overall: Must average ≥70 to proceed, otherwise loop back to interview
3. Validation rules (examples):
   - If no "features" answer → incomplete
   - If "timeline" is unrealistic for "scope" → inconsistent
   - If no "success criteria" → not testable
4. Provide detailed feedback:
   - List specific gaps
   - Suggest follow-up questions
   - Mark for manual review if uncertain
5. Return signals:
   - `"requirements_valid"` → advance to Phase 3 (architecture)
   - `"requirements_incomplete"` → loop back to Phase 2 (interview)

**Success Criteria:**
- Validation scores are computed and logged
- Incomplete requirements are detected
- Feedback is actionable and specific
- Signal selection is correct

---

### Task C3: Port bisset-architect & Paradigm Specialists
**Files:** `orchestrator/agents/bisset_architect.py`, `orchestrator/agents/bisset_architect_oop.py`, `orchestrator/agents/bisset_architect_functional.py`, `orchestrator/agents/bisset_architect_dataoriented.py`

**Requirements:**
1. **bisset-architect (dispatcher):**
   - Orchestrate 3 paradigm specialists sequentially (or in parallel if `async_mode=true`)
   - Call each specialist: OOP, Functional, Data-Oriented
   - Each returns proposal (markdown with architecture design + self-assessment score 0-100)
   - Store proposals via `workflow_store_proposal(paradigm, content)`
   - Retrieve & score proposals via `workflow_list_proposals()`
   - Return signal: `"tasks_ready"` to advance to Phase 4

2. **bisset-architect-oop:**
   - Design OOP architecture (classes, inheritance, polymorphism)
   - Base design on frozen requirements
   - Include: domain objects, services, repositories, error handling
   - Self-assess design: How well does it satisfy requirements? (0-100)
   - Output: Markdown proposal with code sketches

3. **bisset-architect-functional:**
   - Design functional architecture (pure functions, immutability, composition)
   - Alternative to OOP (not better, just different)
   - Include: data transformations, pipelines, side effects management
   - Self-assess design (0-100)
   - Output: Markdown proposal with code sketches

4. **bisset-architect-dataoriented:**
   - Design data-oriented architecture (entity-component, data arrays, cache efficiency)
   - Focus on performance & memory layout
   - Include: data structures, access patterns, concurrency
   - Self-assess design (0-100)
   - Output: Markdown proposal with code sketches

**Success Criteria:**
- 3 proposals are generated and stored
- Each proposal includes self-assessment score
- Proposals can be retrieved and compared
- Signal `tasks_ready` is sent to advance phase
- Async mode (if enabled) runs specialists in parallel

---

### Task C4: Port bisset-test-gherkin Agent
**File:** `orchestrator/agents/bisset_test_gherkin.py` (new)

**Requirements:**
1. **Phase 4 (Feature Generation):**
   - For each task from work breakdown:
     - Parse acceptance_criteria (Gherkin Given-When-Then format)
     - Write to `{project_path}/features/{task_id}.feature`
     - Parse negative_acceptance_criteria
     - Write to `{project_path}/features/{task_id}.negative.feature`
   - Validate Gherkin syntax (correct Given-When-Then structure)
   - Return signal: `"features_written"`

2. **Phase 6 (Coverage Gate):**
   - Run full BDD suite: `pytest {project_path}/features/` (or configured runner)
   - Parse output: passed, failed, total, coverage %
   - Check: coverage_pct >= bdd_coverage_threshold (default 80%)
   - If passing:
     - Return signal: `"coverage_passed"` → workflow complete
   - If failing:
     - Return signal: `"coverage_failed"` → loop back to Phase 5

3. Feature file format (standard Gherkin):
   ```gherkin
   Feature: User Authentication
     Scenario: User login with valid credentials
       Given a registered user
       When they submit username and password
       Then they receive a valid JWT token
   ```

**Success Criteria:**
- Feature files are generated from task acceptance criteria
- Feature files are syntactically valid Gherkin
- BDD runner output is parsed correctly
- Coverage gate logic is correct
- Signals are sent at appropriate times

---

### Task C5: Port bisset-implement Agent & Domain Specialists
**Files:** `orchestrator/agents/bisset_implement.py`, `orchestrator/agents/bisset_backend.py`, `orchestrator/agents/bisset_frontend.py`, `orchestrator/agents/bisset_database.py`, `orchestrator/agents/bisset_cloud.py`, `orchestrator/agents/bisset_devops.py`, `orchestrator/agents/bisset_embedded.py`, `orchestrator/agents/bisset_ux.py`, `orchestrator/agents/bisset_docs.py`

**Requirements:**
1. **bisset-implement (dispatcher):**
   - Loop:
     - Call `workflow_next_task()` to get pending task
     - Determine task domain (backend, frontend, database, cloud, devops, embedded, ux)
     - Dispatch to domain specialist
     - Wait for implementation
     - Call `workflow_run_tests(task_id)` to verify
     - If passing: `workflow_accept_task_result(...)` → mark done
     - If failing: provide feedback to specialist, retry
   - After all tasks done: dispatch bisset-docs
   - Return signal: `"implementation_complete"`

2. **Domain Specialists (8 agents):**
   - Each specialist receives: task_id, title, description, acceptance_criteria
   - Each implements the feature in their domain
   - Each ensures acceptance tests pass
   - Each reports back with: summary, files_changed, test_results
   - Examples:
     - **bisset-backend:** HTTP endpoints, business logic, database queries
     - **bisset-frontend:** React/Vue/Svelte components, styling, state management
     - **bisset-database:** Schema, migrations, queries, indexes
     - **bisset-cloud:** AWS/GCP/Azure resources, IaC (Terraform/CDK)
     - **bisset-devops:** CI/CD pipelines, Docker, Kubernetes
     - **bisset-embedded:** MCU code, drivers, firmware
     - **bisset-ux:** UI design, interaction specs, accessibility
     - **bisset-docs:** README, API reference, user guides, developer onboarding

3. **bisset-docs (special):**
   - Runs after implementation complete
   - Updates: README, API reference, architecture docs, user guides
   - Calls `bisset-ux` for user flow documentation
   - Returns: files_updated

**Success Criteria:**
- All tasks are dispatched to correct specialist
- Specialists implement and test features
- Tests pass before task is marked done
- Documentation is comprehensive
- Signal `implementation_complete` is sent

---

## Phase D: Testing & Hardening (Parallel with C)

### Task D1: Integration Tests
**File:** `orchestrator/tests/test_integration.py` (new)

**Requirements:**
1. Test MCP protocol compliance:
   - Tools are discoverable
   - Tool schemas are valid
   - Responses follow Claude SDK format
2. Test session lifecycle:
   - Create session → interview → freeze spec → architect → gherkin → implement → done
3. Test error handling:
   - Invalid inputs are rejected with correct error codes
   - "No active session" error when expected
   - Test coverage too low error blocks task acceptance
4. Test state recovery:
   - Crash in middle of implementation
   - Restart & recover session state
   - Replay from events log
5. Mock Claude SDK for testing (don't require API key)

**Success Criteria:**
- All tests pass
- Coverage >80%
- Errors are handled gracefully

---

### Task D2: Load Testing
**File:** `orchestrator/tests/test_load.py` (new)

**Requirements:**
1. Test concurrent sessions:
   - 10 concurrent sessions creating projects
   - Each session performs interview, freeze spec, architecture
   - Verify no data corruption or race conditions
2. Test storage layer:
   - Verify WAL mode is working (concurrent readers)
   - Stress test with large feature files (>1MB)
   - Test schema integrity after migration
3. Measure performance:
   - workflow_next_task() latency
   - workflow_run_tests() latency
   - Database query times

**Success Criteria:**
- 10 concurrent sessions complete without errors
- No data corruption or race conditions
- Performance is acceptable (<1s for most operations)

---

### Task D3: Crash Recovery & State Repair
**File:** `orchestrator/agents/crash_recovery.py` (new), updates to `engine.py`

**Requirements:**
1. Implement crash recovery:
   - On restart, check for incomplete sessions
   - Retrieve events log via `workflow_get_events()`
   - Replay events to reconstruct state
   - Resume from last known good point
2. Implement state repair:
   - Detect corrupt state (e.g., task marked done but no test results)
   - Fix automatically or flag for manual review
3. Add debug tools:
   - `workflow_repair_session(session_id)` — attempt auto-repair
   - `workflow_inspect_events(session_id, limit)` — inspect event log
   - `workflow_rollback_task(task_id)` — revert task to pending

**Success Criteria:**
- Crashed sessions can be recovered
- State corruption is detected and fixed
- Debug tools work correctly
- No manual intervention needed for most failures

---

## Phase E: Configuration & Deployment

### Task E1: Update Configuration Files
**Files:** `.env.example`, `orchestrator/requirements.txt`, `docker-compose.yml`, `Dockerfile`

**Requirements:**
1. `.env.example`:
   ```bash
   DATABASE_PATH=./orchestrator/workflow_server/workflow.db
   WORKFLOW_SERVER_PORT=8765
   WORKFLOW_PRETTY_JSON_LOGS=1
   BDD_COVERAGE_THRESHOLD=80
   ```

2. `requirements.txt`:
   - Add: `anthropic>=0.20.0` (or latest Claude SDK)
   - Add: `fastapi>=0.100.0`
   - Add: `uvicorn>=0.23.0`
   - Add: `pydantic>=2.0.0`
   - Remove: FastMCP reference (if any)

3. `docker-compose.yml`:
   - Service for workflow_server (port 8765)
   - Service for mcp_server (STDIO)
   - Volume for database persistence
   - Environment variables from `.env`

4. `Dockerfile`:
   - Python 3.10+ base image
   - Install dependencies
   - Expose port 8765
   - Run workflow_server by default

**Success Criteria:**
- Environment variables are documented
- Dependencies are specified correctly
- Docker containers build and run
- Database persists across container restarts

---

## Success Criteria (Overall)

1. **Architecture:** Two-tier (STDIO proxy + HTTP backend) is working end-to-end
2. **Features:** All 6 workflow phases are functional
3. **Storage:** Schema v7 is implemented, migration works
4. **Tools:** All 20+ tools are implemented and Claude SDK compatible
5. **Agents:** All 9 agents (interview, requirements, architect+3, gherkin, implement+8) are ported
6. **Testing:** Integration tests pass, load tests pass, crash recovery works
7. **Documentation:** API reference, architecture diagrams, implementation guide, code examples exist
8. **Configuration:** .env, requirements.txt, docker-compose.yml are updated
9. **Backward Compatibility:** Existing Copilot CLI workflows still work (or migration path documented)

---

## Deliverables Checklist

### Phase A (Foundation)
- [x] Task A1: Schema v7 migration — `claude/orchestrator/workflow_server/storage.py`
- [x] Task A2: Claude SDK MCP server — `claude/orchestrator/mcp_server/server.py`
- [x] Task A3: Model-aware routing — `claude/orchestrator/workflow_server/engine.py`
- [x] Task A4: Response wrappers — `claude/orchestrator/workflow_server/app.py`
- [x] Task A5: Prompt caching — `claude/orchestrator/mcp_server/prompts.py`
- [x] Task A6: Async mode — background_jobs table + `workflow_status` endpoint + `async_mode` flag in `workflow_start`

### Phase B (Documentation)
- [x] Task B1: API reference — `docs/api-reference.md`
- [x] Task B2: Architecture diagrams & ADRs — `docs/architecture-claude.md`
- [x] Task B3: Implementation guide — `docs/implementation-guide.md`
- [x] Task B4: Code examples (6 files) — `docs/examples/01_*.py` through `docs/examples/06_*.py`

### Phase C (Agents)
- [ ] Task C1: bisset-interview
- [ ] Task C2: bisset-requirements-validate
- [ ] Task C3: bisset-architect + 3 paradigm specialists
- [ ] Task C4: bisset-test-gherkin
- [ ] Task C5: bisset-implement + 8 domain specialists

### Phase D (Testing)
- [ ] Task D1: Integration tests
- [ ] Task D2: Load tests
- [ ] Task D3: Crash recovery

### Phase E (Deployment)
- [x] Task E1: Configuration files — `claude/.env.example`, `claude/requirements.txt`, `docker-compose.yml`, `Dockerfile`

---

## Key Guidelines

1. **Follow the Plan:** The detailed specification in `/plan.md` is your contract. Refer to it for API signatures, data models, and design decisions.

2. **Code Quality:**
   - All code must be well-commented
   - Use type hints (Python 3.10+)
   - Follow PEP 8 style guide
   - Aim for >80% test coverage

3. **Backward Compatibility:**
   - Existing Copilot CLI deployments should continue to work
   - If breaking changes are necessary, document migration path

4. **Error Handling:**
   - All errors must include error code, message, and optional details
   - Follow plan.md error response format
   - Log all errors for debugging

5. **Testing:**
   - Unit tests for individual components
   - Integration tests for workflows
   - Load tests for concurrency
   - Always run full test suite before committing

6. **Documentation:**
   - Keep code and docs in sync
   - Use Markdown for all docs
   - Include examples for each major feature
   - Update this IMPLEMENTATION_PROMPT.md if requirements change

---

## Communication

- Report progress using git commits with meaningful messages
- Tag commits with phase: `[Phase A]`, `[Phase B]`, etc.
- If you encounter blockers, document the issue and propose solutions
- After each completed phase, verify all success criteria are met

---

## Getting Started

1. Read `/plan.md` carefully (all sections, especially Part 3: Specifications)
2. Start with **Phase A Task A1** (schema migration) — this unblocks everything
3. Implement tasks in dependency order (see todo_deps in SQL database)
4. Run tests after each task
5. Commit frequently with clear messages
6. Update this checklist as you complete tasks

---

**Good luck! This is a high-quality project. Take time to implement it right.**
