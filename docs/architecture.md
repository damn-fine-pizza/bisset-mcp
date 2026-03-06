# BissetMCP — Documentazione dell'architettura

## Indice

1. [Panoramica](#1-panoramica)
2. [Struttura del repository](#2-struttura-del-repository)
3. [Componenti del sistema](#3-componenti-del-sistema)
   - 3.1 [MCP Context Server](#31-mcp-context-server)
   - 3.2 [Orchestrator](#32-orchestrator)
   - 3.3 [Agenti Scrum](#33-agenti-scrum)
4. [Flusso multi-agente Scrum](#4-flusso-multi-agente-scrum)
5. [Dettaglio dei ruoli e system prompt](#5-dettaglio-dei-ruoli-e-system-prompt)
6. [Contratto API](#6-contratto-api)
7. [Configurazione e variabili d'ambiente](#7-configurazione-e-variabili-dampiente)
8. [Avvio con Docker Compose](#8-avvio-con-docker-compose)
9. [Aggiungere un nuovo agente](#9-aggiungere-un-nuovo-agente)
10. [Note su estensioni future](#10-note-su-estensioni-future)

---

## 1. Panoramica

BissetMCP è un sistema multi-agente che simula un **team Scrum completo** composto da figure senior. Ogni membro del team è un agente autonomo (servizio Flask + LLM OpenAI) che:

- riceve un task via webhook HTTP
- legge il contesto accumulato dagli agenti precedenti dal **MCP Context Server**
- produce il proprio output in markdown (charter, backlog, wireframe, schema SQL, codice, ecc.)
- scrive il risultato nel contesto condiviso, rendendolo disponibile agli agenti successivi

L'**Orchestrator** coordina l'intera pipeline esposta tramite un singolo endpoint `POST /sprint`.

```
Client
  │
  └─ POST /sprint {"project": "..."} ──► Orchestrator (:8080)
                                               │
                                     ┌─────────┼──────────────────┐
                                     │         │                  │
                                     ▼         ▼                  ▼
                               MCP Context  Agent 1 ... N    (sequenziale)
                               Server :3000
                               (store condiviso)
```

---

## 2. Struttura del repository

```
BissetMCP/
├── docs/
│   └── architecture.md          ← questo file
├── mcp-example/
│   ├── index.js                 ← MCP Context Server (Node.js/Express)
│   ├── package.json
│   └── start-mcp.sh             ← helper per avvio standalone senza Docker
└── orchestrator/
    ├── .env.example             ← template variabili d'ambiente
    ├── docker-compose.yml       ← definizione di tutti i servizi
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

## 3. Componenti del sistema

### 3.1 MCP Context Server

**Percorso:** `mcp-example/`  
**Runtime:** Node.js 18, Express  
**Porta:** `3000`

Store in-memory condiviso tra tutti gli agenti. Persiste il contesto dello sprint corrente (progetto + output accumulati di ogni agente) per tutta la durata della pipeline.

#### Endpoints

| Metodo | Path | Descrizione |
|--------|------|-------------|
| `GET` | `/context` | Restituisce il contesto corrente (JSON) |
| `POST` | `/context` | Sovrascrive il contesto con il body JSON |
| `DELETE` | `/context` | Resetta il contesto a `{ tasks: [] }` |
| `GET` | `/health` | Health check — risponde `{ status: "ok" }` |

#### Struttura del contesto

```json
{
  "project": "Descrizione del progetto inviata dall'utente",
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

> **Nota:** il context server è in-memory. Al riavvio del container il contesto viene perso. Per persistenza vedere [§10](#10-note-su-estensioni-future).

---

### 3.2 Orchestrator

**Percorso:** `orchestrator/orchestrator/app.py`  
**Runtime:** Python 3.11, Flask  
**Porta:** `8080`

Espone due endpoint:

#### `POST /dispatch`

Dispatch diretto a un singolo agente per nome. Utile per testing o invocazioni one-shot.

```json
// Request
{ "agent": "sw-architect", "task": { "id": "t1", "action": "..." } }

// Response
{ "dispatched_to": "agent-sw-architect", "status_code": 200, "response": { ... } }
```

#### `POST /sprint`

Avvia la pipeline Scrum completa in sequenza. Ogni agente viene chiamato nell'ordine corretto e vede il lavoro di tutti quelli precedenti.

```json
// Request
{ "project": "App di prenotazione ristoranti con pagamenti e recensioni" }

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

**Pipeline Scrum (ordine fisso):**

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

Ogni step ha un timeout di **120 secondi** per completare la chiamata LLM.

---

### 3.3 Agenti Scrum

Ogni agente segue la stessa struttura interna:

```
/webhook (POST)
    │
    ├── 1. Legge il contesto completo da MCP  GET /context
    │         (project + output di tutti gli agenti precedenti)
    │
    ├── 2. Costruisce il messaggio per il LLM
    │         system:  system prompt specifico del ruolo
    │         user:    contesto accumulato + "produce your contribution"
    │
    ├── 3. Chiama OpenAI Chat Completions API
    │         model: LLM_MODEL (default: gpt-4o-mini)
    │
    ├── 4. Scrive l'output nel contesto MCP   POST /context
    │
    └── 5. Risponde { status, role, output }
```

**Pattern comune a tutti gli agenti** (template):

```python
from flask import Flask, request, jsonify
import os, requests
from openai import OpenAI

ROLE = "<nome del ruolo>"
MCP_URL = os.environ.get('MCP_URL', 'http://mcp:3000')
MODEL   = os.environ.get('LLM_MODEL', 'gpt-4o-mini')
client  = OpenAI(api_key=os.environ.get('LLM_API_KEY', ''))
app     = Flask(__name__)

SYSTEM_PROMPT = """..."""  # specifico per ruolo

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

## 4. Flusso multi-agente Scrum

```
POST /sprint
{"project": "App di prenotazione ristoranti con pagamenti e recensioni"}
        │
        ▼
[Orchestrator] Reset MCP context → inizializza {"project": "...", "tasks": []}
        │
        ├──► [Senior Product Manager]
        │         Legge: solo "project"
        │         Produce: Project Charter (vision, KPI, roadmap, rischi)
        │         Scrive: contesto += { by: "Senior Product Manager", output: "..." }
        │
        ├──► [Product Owner]
        │         Legge: project + charter del PM
        │         Produce: Backlog (epics, user stories, acceptance criteria, story points, MoSCoW, Sprint 1)
        │         Scrive: contesto += { by: "Product Owner", output: "..." }
        │
        ├──► [Senior UX Designer]
        │         Legge: project + charter + backlog
        │         Produce: UX doc (personas, user flows, wireframe ASCII, design system)
        │         Scrive: contesto += { by: "Senior UX Designer", output: "..." }
        │
        ├──► [Senior Database Engineer]
        │         Legge: project + charter + backlog + UX
        │         Produce: Schema SQL DDL, ER diagram, indici, migration notes
        │         Scrive: contesto += { by: "Senior Database Engineer", output: "..." }
        │
        ├──► [Software Architect]
        │         Legge: tutto il precedente
        │         Produce: architettura (componenti, tech stack, API contract, NFR)
        │         Scrive: contesto += { by: "Software Architect", output: "..." }
        │
        ├──► [Senior Backend Developer]
        │         Legge: tutto il precedente (incluso schema DB e API contract)
        │         Produce: codice backend (modelli, endpoint critici, test)
        │         Scrive: contesto += { by: "Senior Backend Developer", output: "..." }
        │
        └──► [Senior Frontend Developer]
                  Legge: tutto il precedente (incluso UX e API contract)
                  Produce: codice frontend React/TS (componenti, hooks, routing, state)
                  Scrive: contesto += { by: "Senior Frontend Developer", output: "..." }
                         │
                         ▼
              [Orchestrator] Restituisce sprint_results + final_context
```

---

## 5. Dettaglio dei ruoli e system prompt

### Senior Product Manager (`agent-senior-product-manager`)
**Porta:** 8108  
**Output atteso:** Project Charter strutturato

```
Produce in markdown:
- Executive summary e vision
- Goals e success metrics (KPI)
- Scope (in/out)
- Stakeholder map
- Roadmap ad alto livello (milestones)
- Rischi e dipendenze
```

---

### Product Owner (`agent-product-owner`)
**Porta:** 8102  
**Output atteso:** Product Backlog pronto per lo sviluppo

```
Produce in markdown:
- Epics (2-4)
- User stories (As a <role> I want <feature> so that <benefit>)
- Acceptance criteria (Given/When/Then)
- Story points (Fibonacci: 1,2,3,5,8,13)
- MoSCoW priority
- Sprint 1 backlog selection (8-13 punti)
```

---

### Senior UX Designer (`agent-ux-designer-senior`)
**Porta:** 8107  
**Output atteso:** UX Design Document

```
Produce in markdown:
- User personas (2-3, con goals e pain points)
- User flows (step-by-step per i journey principali)
- Wireframe di ogni schermata principale (ASCII art)
- Navigation map / information architecture
- Component inventory
- Design system: palette colori, tipografia, spacing tokens
```

---

### Senior Database Engineer (`agent-senior-database-engineer`)
**Porta:** 8105  
**Output atteso:** Database Design Document

```
Produce in markdown:
- Entity-Relationship diagram (testuale/ASCII)
- SQL DDL completo (PostgreSQL): CREATE TABLE, vincoli, FK
- Strategia degli indici (colonne e motivazione)
- Dati di seed di esempio
- Note sulla migration strategy
- Considerazioni su caching (Redis keys, TTL)
```

---

### Software Architect (`agent-sw-architect`)
**Porta:** 8101  
**Output atteso:** Architecture Document

```
Produce in markdown:
- Panoramica dell'architettura (components diagram ASCII)
- Tech stack con motivazione (backend, frontend, DB, infra)
- API contract completo (metodo, path, request body, response)
- Strategia di autenticazione/autorizzazione
- NFR: scalabilità, sicurezza, osservabilità
- Struttura cartelle/moduli per backend e frontend
```

---

### Senior Backend Developer (`agent-senior-developer`)
**Porta:** 8103  
**Output atteso:** Backend Implementation Document

```
Produce in markdown:
- File tree del modulo/servizio
- Modelli dati / DTO (dataclass Python o TypeScript interface)
- Implementazione dei 3 endpoint critici (codice completo, non pseudocodice)
- Data access layer (ORM o query raw)
- Pattern di validazione input e gestione errori
- Test unitari per la business logic critica
```

---

### Senior Frontend Developer (`agent-senior-frontend-developer`)
**Porta:** 8104  
**Output atteso:** Frontend Implementation Document

```
Produce in markdown:
- Component tree / struttura pagine
- Implementazione dei 3 componenti principali (React + TypeScript)
- API integration layer (custom hooks o service functions)
- State management (Zustand / Redux Toolkit / React Query)
- Configurazione routing
- Note sul layout responsivo in linea con i wireframe UX
```

---

### Senior QA Engineer (`agent-senior-qa-engineer`)
**Porta:** 8106  
**Nota:** Presente come servizio ma **non incluso nel pipeline Scrum di default**. Può essere invocato singolarmente via `/dispatch` oppure aggiunto a `SCRUM_PIPELINE` nell'orchestrator.

---

## 6. Contratto API

### MCP Context Server `:3000`

```
GET    /context          → 200 { project, tasks: [...] }
POST   /context          → 200 { ok: true }         body: { project, tasks }
DELETE /context          → 200 { ok: true }         reset a { tasks: [] }
GET    /health           → 200 { status: "ok" }
```

### Orchestrator `:8080`

```
POST /dispatch
  body:     { "agent": "<nome>", "task": { ... } }
  response: { "dispatched_to": "agent-<nome>", "status_code": N, "response": { ... } }

POST /sprint
  body:     { "project": "<descrizione libera del progetto>" }
  response: {
    "sprint_results": [
      { "agent": "senior-product-manager", "status_code": 200, "output": "..." },
      ...
    ],
    "final_context": { "project": "...", "tasks": [...] }
  }
```

### Agenti `:800x`

```
POST /webhook
  body:     { "project": "...", ...payload opzionale }
  response: { "status": "ok", "role": "<nome ruolo>", "output": "<markdown>" }
```

---

## 7. Configurazione e variabili d'ambiente

Creare un file `.env` nella cartella `orchestrator/` a partire da `.env.example`:

```bash
cp orchestrator/.env.example orchestrator/.env
# editare .env e inserire la chiave OpenAI
```

| Variabile | Default | Descrizione |
|-----------|---------|-------------|
| `LLM_API_KEY` | _(obbligatoria)_ | API key del provider LLM |
| `LLM_MODEL` | `gpt-4o-mini` | Modello LLM da usare per tutti gli agenti |
| `MCP_URL` | `http://mcp:3000` | URL interno del context server (non modificare in Docker) |

> **Suggerimento modelli:**
> - `gpt-4o-mini` — veloce, economico, ottimo per sviluppo e test
> - `gpt-4o` — output di qualità superiore, consigliato per uso reale
> - `gpt-4-turbo` — bilanciamento qualità/costo

Il `docker-compose.yml` utilizza **YAML anchors** (`x-agent-env`) per iniettare le variabili in tutti gli agenti senza duplicazioni:

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

## 8. Avvio con Docker Compose

```bash
cd orchestrator

# 1. Configurare le variabili d'ambiente
cp .env.example .env
# editare .env: inserire LLM_API_KEY

# 2. Build e avvio di tutti i servizi
docker-compose up -d --build

# 3. Verificare che i servizi siano up
docker-compose ps

# 4. Avviare uno sprint completo
curl http://localhost:8080/sprint \
  -X POST \
  -H 'Content-Type: application/json' \
  -d '{"project": "App di prenotazione ristoranti con pagamenti e recensioni"}'

# 5. (Opzionale) Dispatch a singolo agente
curl http://localhost:8080/dispatch \
  -X POST \
  -H 'Content-Type: application/json' \
  -d '{"agent": "sw-architect", "task": {"id": "t1", "action": "review architecture"}}'

# 6. Leggere il contesto accumulato direttamente
curl http://localhost:3000/context

# 7. Log di un agente
docker-compose logs -f agent-senior-developer
```

### Avvio standalone del solo MCP server (senza Docker)

```bash
cd mcp-example
./start-mcp.sh start    # avvia il context server su :3000
./start-mcp.sh status   # verifica lo stato
./start-mcp.sh logs     # segue i log
./start-mcp.sh stop     # ferma il server
```

---

## 9. Aggiungere un nuovo agente

### Passo 1 — Creare la cartella dell'agente

```bash
mkdir -p orchestrator/agents/agent-<nome>
```

### Passo 2 — `app.py`

Copiare il template di §3.3 e personalizzare:
- `ROLE` — nome del ruolo (es. `"Senior Security Engineer"`)
- `SYSTEM_PROMPT` — istruzioni specifiche per il ruolo
- `max_tokens` — aumentare per output più lunghi (es. `2500`)

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

### Passo 3 — `requirements.txt`

```
flask==2.2.5
requests==2.31.0
openai>=1.0.0
```

### Passo 4 — Aggiungere al `docker-compose.yml`

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

### Passo 5 (opzionale) — Inserire nella pipeline Scrum

In `orchestrator/orchestrator/app.py`, aggiungere il nome alla lista `SCRUM_PIPELINE` nella posizione corretta:

```python
SCRUM_PIPELINE = [
    'senior-product-manager',
    'product-owner',
    'ux-designer-senior',
    'senior-database-engineer',
    'sw-architect',
    'senior-security-engineer',   # ← aggiunto dopo l'architettura
    'senior-developer',
    'senior-frontend-developer',
]
```

---

## 10. Note su estensioni future

### Persistenza del contesto

Il MCP context server usa un `let context = {}` in memoria. Per persistenza:
- **Redis** — sostituire la variabile in-memory con `ioredis` o `redis` npm package
- **PostgreSQL** — aggiungere una tabella `sprint_context(id, project, tasks jsonb)`
- **File system** — scrivere su disco JSON (adatto solo per sviluppo locale)

### Parallelismo parziale

Alcuni agenti non dipendono l'uno dall'altro e potrebbero girare in parallelo. Esempio:
- `senior-database-engineer` e `ux-designer-senior` potrebbero partire entrambi dopo il `product-owner`

Per implementarlo nell'orchestrator, sostituire la lista piatta con un DAG:

```python
PIPELINE_STAGES = [
    ['senior-product-manager'],
    ['product-owner'],
    ['ux-designer-senior', 'senior-database-engineer'],  # paralleli
    ['sw-architect'],
    ['senior-developer', 'senior-frontend-developer'],   # paralleli
]
```

Usare `concurrent.futures.ThreadPoolExecutor` per eseguire gli agenti di ogni stage in parallelo.

### Integrazione con Temporal

Il `docker-compose.yml` è pensato per essere un punto di partenza locale. Per ambienti di produzione è consigliabile sostituire la pipeline sincrona con workflow **Temporal**:
- ogni step della pipeline diventa una `Activity`
- il workflow gestisce retry, timeout e compensazioni automaticamente
- vedere la [documentazione Temporal](https://docs.temporal.io/)

### Modelli alternativi

Il parametro `LLM_MODEL` permette di usare qualsiasi modello compatibile con l'API OpenAI Chat Completions. Per usare modelli locali (es. via **Ollama** o **LM Studio**) è sufficiente sovrascrivere il `base_url` nel client:

```python
client = OpenAI(
    api_key=os.environ.get('LLM_API_KEY', 'ollama'),
    base_url=os.environ.get('LLM_BASE_URL', 'http://localhost:11434/v1'),
)
```

Aggiungere `LLM_BASE_URL` come variabile d'ambiente nel `.env` e nel `docker-compose.yml`.

### Output persistente dello sprint

L'endpoint `/sprint` restituisce tutto in risposta HTTP ma non salva su file. Per generare automaticamente un documento markdown dello sprint:

```python
# in orchestrator/app.py, alla fine di /sprint
import json, pathlib, datetime
out_dir = pathlib.Path("/srv/sprints")
out_dir.mkdir(exist_ok=True)
ts = datetime.datetime.utcnow().strftime("%Y%m%dT%H%M%S")
(out_dir / f"sprint_{ts}.json").write_text(json.dumps(sprint_results, indent=2))
```

Montare `/srv/sprints` come volume nel `docker-compose.yml` per accedervi dall'host.
