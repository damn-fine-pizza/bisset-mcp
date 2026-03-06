# BissetMCP — Architecture Documentation

## Table of Contents

1. [Overview](#1-overview)
2. [Repository Structure](#2-repository-structure)
3. [System Components](#3-system-components)
   - 3.1 [MCP Context Server](#31-mcp-context-server)
   - 3.2 [Orchestrator](#32-orchestrator)
   - 3.3 [Scrum Agents](#33-scrum-agents)
4. [Multi-Agent Scrum Flow](#4-multi-agent-scrum-flow)
5. [Role Details and System Prompts](#5-role-details-and-system-prompts)
6. [API Contract](#6-api-contract)
7. [Configuration and Environment Variables](#7-configuration-and-environment-variables)
8. [Starting with Docker Compose](#8-starting-with-docker-compose)
9. [Adding a New Agent](#9-adding-a-new-agent)
10. [Notes on Future Extensions](#10-notes-on-future-extensions)

---

## 1. Overview

BissetMCP is a multi-agent system that simulates a **complete Scrum team** composed of senior roles. Each team member is an autonomous agent (Flask service + OpenAI LLM) that:

- receives a task via HTTP webhook
- reads the context accumulated by previous agents from the **MCP Context Server**
- produces its own output in markdown (charter, backlog, wireframe, SQL schema, code, etc.)
- writes the result to the shared context, making it available to subsequent agents

The **Orchestrator** coordinates the entire pipeline exposed through a single `POST /sprint` endpoint.

```
Client
  │
  └─ POST /sprint {"project": "..."} ──► Orchestrator (:8080)
                                               │
                                     ┌─────────┼──────────────────┐
                                     │         │                  │
                                     ▼         ▼                  ▼
                               MCP Context  Agent 1 ... N    (sequential)
                               Server :3000
                               (shared store)
```

---

## 2. Repository Structure

```
BissetMCP/
├── docs/
│   └── architecture.md          ← this file
├── mcp-example/
│   ├── index.js                 ← MCP Context Server (Node.js/Express)
│   ├── package.json
│   └── start-mcp.sh             ← helper for standalone startup without Docker
└── orchestrator/
    ├── .env.example             ← environment variables template
    ├── docker-compose.yml       ← definition of all services
    ├── orchestrator/
    │   ├── app.py               ← Orchestrator Flask (/dispatch + /sprint)
    │   └── requirements.txt
    └── agents/
        ├── agent-senior-product-manager/
        │   ├── app.py
        │   └── requirements.txt
        ├── agent-product-owner/
        │   ├── app.py
        │   └── requirements.txt
        ├── agent-ux-designer-senior/
        │   ├── app.py
        │   └── requirements.txt
        ├── agent-senior-database-engineer/
        │   ├── app.py
        │   └── requirements.txt
        ├── agent-sw-architect/
        │   ├── app.py
        │   └── requirements.txt
        ├── agent-senior-developer/
        │   ├── app.py
        │   └── requirements.txt
        ├── agent-senior-frontend-developer/
        │   ├── app.py
        │   └── requirements.txt
        └── agent-senior-qa-engineer/
            ├── app.py
            └── requirements.txt
```

---

## 3. System Components

### 3.1 MCP Context Server

**Path:** `mcp-example/`
**Runtime:** Node.js 18, Express
**Port:** `3000`

In-memory store shared across all agents. Persists the current sprint context (project + accumulated output of each agent) for the duration of the pipeline.

#### Endpoints

| Method | Path | Description |
|--------|------|-------------|
| `GET` | `/context` | Returns the current context (JSON) |
| `POST` | `/context` | Overwrites the context with the JSON body |
| `DELETE` | `/context` | Resets the context to `{ tasks: [] }` |
| `GET` | `/health` | Health check — responds with `{ status: "ok" }` |

#### Context Structure

```json
{
  "project": "Project description sent by the user",
  "tasks": [
    {
      "by": "Senior Product Manager",
      "task": { "project": "..." },
      "output": "# Project Charter\n..."
    },
    {
      "by": "Product Owner",
      "task": { "project": "..." },
      "output": "# Product Backlog\n..."
    }
  ]
}
```

> **Note:** the context server is in-memory. When the container restarts, the context is lost. For persistence see [§10](#10-notes-on-future-extensions).

---

### 3.2 Orchestrator

**Path:** `orchestrator/orchestrator/app.py`
**Runtime:** Python 3.11, Flask
**Port:** `8080`

Exposes two endpoints:

#### `POST /dispatch`

Direct dispatch to a single agent by name. Useful for testing or one-shot invocations.

```json
// Request
{ "agent": "sw-architect", "task": { "id": "t1", "action": "..." } }

// Response
{ "dispatched_to": "agent-sw-architect", "status_code": 200, "response": { ... } }
```

#### `POST /sprint`

Starts the complete Scrum pipeline in sequence. Each agent is called in the correct order and sees the work of all previous ones.

```json
// Request
{ "project": "Restaurant booking app with payments and reviews" }

// Response
{
  "sprint_results": [
    { "agent": "senior-product-manager", "status_code": 200, "output": "..." },
    { "agent": "product-owner",          "status_code": 200, "output": "..." },
    ...
  ],
  "final_context": { "project": "...", "tasks": [ ... ] }
}
```

**Scrum Pipeline (fixed order):**

```python
SCRUM_PIPELINE = [
    'senior-product-manager',
    'product-owner',
    'ux-designer-senior',
    'senior-database-engineer',
    'sw-architect',
    'senior-developer',
    'senior-frontend-developer',
]
```

Each step has a **120-second** timeout to complete the LLM call.

---

### 3.3 Scrum Agents

Each agent follows the same internal structure:

```
/webhook (POST)
    │
    ├── 1. Reads the full context from MCP  GET /context
    │         (project + output of all previous agents)
    │
    ├── 2. Builds the message for the LLM
    │         system:  role-specific system prompt
    │         user:    accumulated context + "produce your contribution"
    │
    ├── 3. Calls OpenAI Chat Completions API
    │         model: LLM_MODEL (default: gpt-4o-mini)
    │
    ├── 4. Writes the output to the MCP context   POST /context
    │
    └── 5. Responds { status, role, output }
```

**Common pattern across all agents** (template):

```python
from flask import Flask, request, jsonify
import os, requests
from openai import OpenAI

ROLE = "<role name>"
MCP_URL = os.environ.get('MCP_URL', 'http://mcp:3000')
MODEL   = os.environ.get('LLM_MODEL', 'gpt-4o-mini')
client  = OpenAI(api_key=os.environ.get('LLM_API_KEY', ''))
app     = Flask(__name__)

SYSTEM_PROMPT = """..."""  # role-specific

def _get_context_summary():
    ctx = requests.get(f"{MCP_URL}/context", timeout=5).json()
    parts = [f"# Project: {ctx.get('project', '')}"]
    for t in ctx.get('tasks', []):
        parts.append(f"\n## {t['by']}\n{t.get('output', '')}")
    return "\n".join(parts)

def _update_context(payload, output):
    ctx = requests.get(f"{MCP_URL}/context", timeout=5).json()
    ctx.setdefault('tasks', []).append({'by': ROLE, 'task': payload, 'output': output})
    requests.post(f"{MCP_URL}/context", json=ctx, timeout=5)

@app.route('/webhook', methods=['POST'])
def webhook():
    payload = request.json or {}
    summary = _get_context_summary()
    resp = client.chat.completions.create(
        model=MODEL,
        messages=[
            {"role": "system", "content": SYSTEM_PROMPT},
            {"role": "user",   "content": f"{summary}\n\nNow produce your contribution as {ROLE}."},
        ],
        max_tokens=2000,
    )
    output = resp.choices[0].message.content
    _update_context(payload, output)
    return jsonify({'status': 'ok', 'role': ROLE, 'output': output})
```

---

## 4. Multi-Agent Scrum Flow

```
POST /sprint
{"project": "Restaurant booking app with payments and reviews"}
        │
        ▼
[Orchestrator] Reset MCP context → initializes {"project": "...", "tasks": []}
        │
        ├──► [Senior Product Manager]
        │         Reads: only "project"
        │         Produces: Project Charter (vision, KPIs, roadmap, risks)
        │         Writes: context += { by: "Senior Product Manager", output: "..." }
        │
        ├──► [Product Owner]
        │         Reads: project + PM charter
        │         Produces: Backlog (epics, user stories, acceptance criteria, story points, MoSCoW, Sprint 1)
        │         Writes: context += { by: "Product Owner", output: "..." }
        │
        ├──► [Senior UX Designer]
        │         Reads: project + charter + backlog
        │         Produces: UX doc (personas, user flows, ASCII wireframe, design system)
        │         Writes: context += { by: "Senior UX Designer", output: "..." }
        │
        ├──► [Senior Database Engineer]
        │         Reads: project + charter + backlog + UX
        │         Produces: SQL DDL schema, ER diagram, indexes, migration notes
        │         Writes: context += { by: "Senior Database Engineer", output: "..." }
        │
        ├──► [Software Architect]
        │         Reads: all previous output
        │         Produces: architecture (components, tech stack, API contract, NFRs)
        │         Writes: context += { by: "Software Architect", output: "..." }
        │
        ├──► [Senior Backend Developer]
        │         Reads: all previous output (including DB schema and API contract)
        │         Produces: backend code (models, critical endpoints, tests)
        │         Writes: context += { by: "Senior Backend Developer", output: "..." }
        │
        └──► [Senior Frontend Developer]
                  Reads: all previous output (including UX and API contract)
                  Produces: frontend React/TS code (components, hooks, routing, state)
                  Writes: context += { by: "Senior Frontend Developer", output: "..." }
                         │
                         ▼
              [Orchestrator] Returns sprint_results + final_context
```

---

## 5. Role Details and System Prompts

### Senior Product Manager (`agent-senior-product-manager`)
**Port:** 8108
**Expected output:** Structured Project Charter

```
Produces in markdown:
- Executive summary and vision
- Goals and success metrics (KPIs)
- Scope (in/out)
- Stakeholder map
- High-level roadmap (milestones)
- Risks and dependencies
```

---

### Product Owner (`agent-product-owner`)
**Port:** 8102
**Expected output:** Development-ready Product Backlog

```
Produces in markdown:
- Epics (2-4)
- User stories (As a <role> I want <feature> so that <benefit>)
- Acceptance criteria (Given/When/Then)
- Story points (Fibonacci: 1,2,3,5,8,13)
- MoSCoW priority
- Sprint 1 backlog selection (8-13 points)
```

---

### Senior UX Designer (`agent-ux-designer-senior`)
**Port:** 8107
**Expected output:** UX Design Document

```
Produces in markdown:
- User personas (2-3, with goals and pain points)
- User flows (step-by-step for main journeys)
- Wireframe of each main screen (ASCII art)
- Navigation map / information architecture
- Component inventory
- Design system: color palette, typography, spacing tokens
```

---

### Senior Database Engineer (`agent-senior-database-engineer`)
**Port:** 8105
**Expected output:** Database Design Document

```
Produces in markdown:
- Entity-Relationship diagram (textual/ASCII)
- Complete SQL DDL (PostgreSQL): CREATE TABLE, constraints, FKs
- Index strategy (columns and rationale)
- Example seed data
- Migration strategy notes
- Caching considerations (Redis keys, TTL)
```

---

### Software Architect (`agent-sw-architect`)
**Port:** 8101
**Expected output:** Architecture Document

```
Produces in markdown:
- Architecture overview (ASCII components diagram)
- Tech stack with rationale (backend, frontend, DB, infra)
- Complete API contract (method, path, request body, response)
- Authentication/authorization strategy
- NFRs: scalability, security, observability
- Folder/module structure for backend and frontend
```

---

### Senior Backend Developer (`agent-senior-developer`)
**Port:** 8103
**Expected output:** Backend Implementation Document

```
Produces in markdown:
- Module/service file tree
- Data models / DTOs (Python dataclass or TypeScript interface)
- Implementation of the 3 critical endpoints (complete code, not pseudocode)
- Data access layer (ORM or raw queries)
- Input validation and error handling patterns
- Unit tests for critical business logic
```

---

### Senior Frontend Developer (`agent-senior-frontend-developer`)
**Port:** 8104
**Expected output:** Frontend Implementation Document

```
Produces in markdown:
- Component tree / page structure
- Implementation of the 3 main components (React + TypeScript)
- API integration layer (custom hooks or service functions)
- State management (Zustand / Redux Toolkit / React Query)
- Routing configuration
- Notes on responsive layout aligned with UX wireframes
```

---

### Senior QA Engineer (`agent-senior-qa-engineer`)
**Port:** 8106
**Note:** Present as a service but **not included in the default Scrum pipeline**. Can be invoked individually via `/dispatch` or added to `SCRUM_PIPELINE` in the orchestrator.

---

## 6. API Contract

### MCP Context Server `:3000`

```
GET    /context          → 200 { project, tasks: [...] }
POST   /context          → 200 { ok: true }         body: { project, tasks }
DELETE /context          → 200 { ok: true }         resets to { tasks: [] }
GET    /health           → 200 { status: "ok" }
```

### Orchestrator `:8080`

```
POST /dispatch
  body:     { "agent": "<name>", "task": { ... } }
  response: { "dispatched_to": "agent-<name>", "status_code": N, "response": { ... } }

POST /sprint
  body:     { "project": "<free-form project description>" }
  response: {
    "sprint_results": [
      { "agent": "senior-product-manager", "status_code": 200, "output": "..." },
      ...
    ],
    "final_context": { "project": "...", "tasks": [...] }
  }
```

### Agents `:800x`

```
POST /webhook
  body:     { "project": "...", ...optional payload }
  response: { "status": "ok", "role": "<role name>", "output": "<markdown>" }
```

---

## 7. Configuration and Environment Variables

Create a `.env` file in the `orchestrator/` folder starting from `.env.example`:

```bash
cp orchestrator/.env.example orchestrator/.env
# edit .env and enter your OpenAI key
```

| Variable | Default | Description |
|-----------|---------|-------------|
| `LLM_API_KEY` | _(required)_ | API key for the LLM provider |
| `LLM_MODEL` | `gpt-4o-mini` | LLM model to use for all agents |
| `MCP_URL` | `http://mcp:3000` | Internal URL of the context server (do not change in Docker) |

> **Model suggestions:**
> - `gpt-4o-mini` — fast, inexpensive, great for development and testing
> - `gpt-4o` — higher quality output, recommended for production use
> - `gpt-4-turbo` — quality/cost balance

The `docker-compose.yml` uses **YAML anchors** (`x-agent-env`) to inject variables into all agents without duplication:

```yaml
x-agent-env: &agent-env
  MCP_URL: http://mcp:3000
  LLM_API_KEY: ${LLM_API_KEY}
  LLM_MODEL: ${LLM_MODEL:-gpt-4o-mini}

services:
  agent-senior-developer:
    environment:
      <<: *agent-env
```

---

## 8. Starting with Docker Compose

```bash
cd orchestrator

# 1. Configure environment variables
cp .env.example .env
# edit .env: enter LLM_API_KEY

# 2. Build and start all services
docker-compose up -d --build

# 3. Verify that services are up
docker-compose ps

# 4. Start a complete sprint
curl http://localhost:8080/sprint \
  -X POST \
  -H 'Content-Type: application/json' \
  -d '{"project": "Restaurant booking app with payments and reviews"}'

# 5. (Optional) Dispatch to a single agent
curl http://localhost:8080/dispatch \
  -X POST \
  -H 'Content-Type: application/json' \
  -d '{"agent": "sw-architect", "task": {"id": "t1", "action": "review architecture"}}'

# 6. Read the accumulated context directly
curl http://localhost:3000/context

# 7. Logs for an agent
docker-compose logs -f agent-senior-developer
```

### Standalone startup of the MCP server only (without Docker)

```bash
cd mcp-example
./start-mcp.sh start    # starts the context server on :3000
./start-mcp.sh status   # checks the status
./start-mcp.sh logs     # follows the logs
./start-mcp.sh stop     # stops the server
```

---

## 9. Adding a New Agent

### Step 1 — Create the agent folder

```bash
mkdir -p orchestrator/agents/agent-<name>
```

### Step 2 — `app.py`

Copy the template from §3.3 and customize:
- `ROLE` — role name (e.g., `"Senior Security Engineer"`)
- `SYSTEM_PROMPT` — role-specific instructions
- `max_tokens` — increase for longer output (e.g., `2500`)

```python
ROLE = "Senior Security Engineer"

SYSTEM_PROMPT = """You are a Senior Security Engineer in a Scrum team.
Based on the architecture and codebase design, produce a security review in markdown:
- Threat model (STRIDE)
- Authentication/authorisation vulnerabilities to watch
- Input validation checklist
- Dependency audit notes
- OWASP Top 10 coverage
Be specific and actionable."""
```

### Step 3 — `requirements.txt`

```
flask==2.2.5
requests==2.31.0
openai>=1.0.0
```

### Step 4 — Add to `docker-compose.yml`

```yaml
  agent-senior-security-engineer:
    image: python:3.11-slim
    container_name: agent-senior-security-engineer
    volumes:
      - ./agents/agent-senior-security-engineer:/srv
    working_dir: /srv
    environment:
      <<: *agent-env
    command: sh -c "pip install -r requirements.txt && python app.py"
    ports:
      - "8109:8000"
```

### Step 5 (optional) — Insert into the Scrum pipeline

In `orchestrator/orchestrator/app.py`, add the name to the `SCRUM_PIPELINE` list in the correct position:

```python
SCRUM_PIPELINE = [
    'senior-product-manager',
    'product-owner',
    'ux-designer-senior',
    'senior-database-engineer',
    'sw-architect',
    'senior-security-engineer',   # ← added after architecture
    'senior-developer',
    'senior-frontend-developer',
]
```

---

## 10. Notes on Future Extensions

### Context Persistence

The MCP context server uses a `let context = {}` in memory. For persistence:
- **Redis** — replace the in-memory variable with `ioredis` or `redis` npm package
- **PostgreSQL** — add a `sprint_context(id, project, tasks jsonb)` table
- **File system** — write JSON to disk (suitable only for local development)

### Partial Parallelism

Some agents do not depend on each other and could run in parallel. Example:
- `senior-database-engineer` and `ux-designer-senior` could both start after `product-owner`

To implement this in the orchestrator, replace the flat list with a DAG:

```python
PIPELINE_STAGES = [
    ['senior-product-manager'],
    ['product-owner'],
    ['ux-designer-senior', 'senior-database-engineer'],  # parallel
    ['sw-architect'],
    ['senior-developer', 'senior-frontend-developer'],   # parallel
]
```

Use `concurrent.futures.ThreadPoolExecutor` to execute the agents of each stage in parallel.

### Integration with Temporal

The `docker-compose.yml` is intended as a local starting point. For production environments it is recommended to replace the synchronous pipeline with **Temporal** workflows:
- each pipeline step becomes an `Activity`
- the workflow handles retries, timeouts, and compensations automatically
- see the [Temporal documentation](https://docs.temporal.io/)

### Alternative Models

The `LLM_MODEL` parameter allows using any model compatible with the OpenAI Chat Completions API. To use local models (e.g., via **Ollama** or **LM Studio**) it is sufficient to override the `base_url` in the client:

```python
client = OpenAI(
    api_key=os.environ.get('LLM_API_KEY', 'ollama'),
    base_url=os.environ.get('LLM_BASE_URL', 'http://localhost:11434/v1'),
)
```

Add `LLM_BASE_URL` as an environment variable in `.env` and in `docker-compose.yml`.

### Persistent Sprint Output

The `/sprint` endpoint returns everything in the HTTP response but does not save to file. To automatically generate a markdown document of the sprint:

```python
# in orchestrator/app.py, at the end of /sprint
import json, pathlib, datetime
out_dir = pathlib.Path("/srv/sprints")
out_dir.mkdir(exist_ok=True)
ts = datetime.datetime.utcnow().strftime("%Y%m%dT%H%M%S")
(out_dir / f"sprint_{ts}.json").write_text(json.dumps(sprint_results, indent=2))
```

Mount `/srv/sprints` as a volume in `docker-compose.yml` to access it from the host.
