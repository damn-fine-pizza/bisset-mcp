# Bisset v2 — Design Document

**Data:** 2026-03-06
**Stato:** Approvato
**Approccio:** Refactor evolutivo (mantiene FastAPI + SQLite + client HTTP + server.sh)

## Obiettivo

Bisset e' un workflow orchestrator MCP che guida Claude (e in futuro Copilot) attraverso pipeline di sviluppo definite dall'utente. Ogni step della pipeline e' validato da test Gherkin eseguiti da Bisset. Claude implementa, Bisset valuta. Il loop converge quando tutti gli scenari passano e la coverage supera la soglia.

Il .feature e' la funzione di reward. Claude e' l'agente. Il codice e' la policy. Bisset e' l'environment. Ogni retry e' un episodio. La coverage e' lo score.

## Architettura

```
Claude Code (o Copilot)
        |  STDIO (MCP protocol)
        v
  mcp_server  --HTTP-->  workflow_server  --SQLite-->  ~/.bisset/bisset.db
  (adapter)               (FastAPI :8765)
                                |
                                v
                          Test Runner
                          (subprocess: pytest/behave/cucumber)
```

- **mcp_server** — adapter STDIO sottile, traduce MCP tool calls in HTTP
- **workflow_server** — tutta la logica: rule engine, gate, test execution
- **bisset.db** — DB centrale in `~/.bisset/bisset.db`, contiene tutti i progetti

Zero logica negli endpoint FastAPI. Tutto nell'engine.

## Modello dati

```
PROJECT
  id, name, path, created_at
  test_runner, test_args, adapter, features_dir

SESSION
  id, project_id, created_at
  workflow_type: new_project | new_feature | generate_tests
  status: active | paused | completed | aborted
  default_rules (JSON — regole DSL)

STEP
  id, session_id, title, description, order
  feature_path (path al file .feature)
  gate: tests_only | human_approval | tests+human
  depends_on (JSON — lista step_id)
  rules_override (JSON — regole specifiche per questo step)
  status: pending | active | passed | failed | skipped
  retries, current_coverage
  gate_result: null | approved | rejected

TEST_RUN
  id, step_id, session_id
  run_at, passed, failed, coverage
  runner_output (log completo)

EVENT
  id, session_id, timestamp
  event_type, step_id
  data (JSON)
```

### Isolamento progetti

- DB centrale: `~/.bisset/bisset.db`
- Letture cross-progetto permesse (project_list, session_list di altri progetti)
- Scritture solo sul progetto lockato — ogni tool che modifica stato usa il project_id implicito dal lock
- Nessun tool operativo accetta project_id come parametro
- Per cambiare progetto: `project_switch` (chiude lock, riapre)
- All'apertura: verifica che il path nel DB corrisponda al cwd

## Tool MCP

### Progetto

| Tool | Tipo | Descrizione |
|------|------|-------------|
| `project_detect` | read | Autodetect progetto dal cwd |
| `project_create` | write | Crea nuovo progetto, locka |
| `project_list` | read | Lista tutti i progetti nel DB |
| `project_switch` | write | Cambia progetto attivo |

### Sessione

| Tool | Tipo | Descrizione |
|------|------|-------------|
| `session_start` | write | Crea sessione, sceglie workflow_type |
| `session_resume` | write | Riprende ultima sessione, copia stato step |
| `session_status` | read | Stato: step, progressi, step corrente |
| `session_list` | read | Lista sessioni di un progetto (cross-progetto ok) |

### Pipeline

| Tool | Tipo | Descrizione |
|------|------|-------------|
| `step_current` | read | Step attivo: descrizione, .feature, criteri |
| `step_run_tests` | write | Bisset esegue test Gherkin, ritorna risultato |
| `step_complete` | write | Tenta di chiudere lo step (gate check + regole DSL) |
| `step_skip` | write | Salta con motivazione obbligatoria |
| `step_list` | read | Lista tutti gli step con stato |
| `step_add` | write | Aggiunge step (titolo, descrizione, gate, posizione) |
| `step_remove` | write | Rimuove step (solo se pending) |
| `step_edit` | write | Modifica titolo/descrizione/gate/feature |
| `step_reorder` | write | Cambia ordine e dipendenze |
| `pipeline_view` | read | Pipeline completa con stato e dipendenze |
| `pipeline_set_rules` | write | Modifica regole DSL della sessione |

### Gherkin

| Tool | Tipo | Descrizione |
|------|------|-------------|
| `step_set_feature` | write | Claude invia contenuto Gherkin, Bisset salva su disco e DB |
| `step_get_feature` | read | Legge il .feature corrente di uno step |
| `step_validate_feature` | read | Dry-run: verifica sintassi Gherkin senza eseguire |

### Intervista

| Tool | Tipo | Descrizione |
|------|------|-------------|
| `interview_answer` | write | Rispondi alla domanda corrente, ricevi la prossima |

### Analisi

| Tool | Tipo | Descrizione |
|------|------|-------------|
| `analyze_codebase` | write | Analizza progetto esistente, genera step + .feature |

### Introspezione

| Tool | Tipo | Descrizione |
|------|------|-------------|
| `pipeline_report` | read | Report: completati, falliti, coverage, tempo |
| `event_log` | read | Audit trail della sessione |

## Rule Engine DSL

Regole dichiarative when/then, valutate in ordine. Prima che matcha vince.

### Variabili

| Variabile | Tipo | Descrizione |
|-----------|------|-------------|
| `tests_pass` | bool | Tutti i test passati |
| `tests_fail` | bool | Almeno un test fallito |
| `coverage` | float | Percentuale coverage ultimo run |
| `retries` | int | Volte che lo step e' stato riprovato |
| `gate` | string | Tipo di gate dello step |
| `no_tests` | bool | Nessun .feature associato |
| `step.order` | int | Posizione nella pipeline |
| `always` | bool | Sempre true (fallback) |

### Azioni

| Azione | Effetto |
|--------|---------|
| `advance` | Step done, passa al prossimo |
| `retry` | Step torna active, incrementa retries |
| `ask_user` | Chiede conferma all'utente |
| `abort` | Ferma la pipeline |
| `skip` | Salta lo step |

### Esempio

```yaml
rules:
  - when: tests_pass AND coverage >= 80
    then: advance
  - when: tests_fail AND retries < 3
    then: retry
  - when: tests_fail AND retries >= 3
    then: ask_user
  - when: tests_pass AND gate == "human_approval"
    then: ask_user
  - when: no_tests
    then: ask_user
  - when: always
    then: abort
```

Ogni sessione ha `default_rules`. Ogni step puo' avere `rules_override`.

## Workflow Types

### new_project

```
1. interview  — domande su scope, stack, vincoli
2. design     — Claude propone architettura, utente approva
3. generate   — Claude genera step + .feature per ogni componente
4. execute    — step-by-step gated: implementa -> test -> advance
```

### new_feature

```
1. analyze    — Claude analizza codebase esistente
2. interview  — domande mirate sulla feature
3. generate   — Claude genera step + .feature per la feature
4. execute    — step-by-step gated
```

### generate_tests

```
1. analyze    — Claude analizza codebase (API, modelli, logic, UI)
2. generate   — Claude genera .feature per tutto
3. validate   — Bisset esegue test, report di cosa passa e cosa no
```

Le fasi sono meta-step che producono gli step concreti. Una volta generati, la sessione ha solo step — le fasi spariscono. L'utente puo' modificare gli step generati prima di eseguirli.

## Test Runner e Adapter

Bisset esegue i test in autonomia. Claude non tocca i risultati.

```
step_run_tests
  -> legge feature_path dello step
  -> subprocess.run([test_runner, feature_path, *test_args])
  -> adapter parsa output
  -> salva in DB: passed, failed, coverage, raw output
  -> applica regole DSL
  -> ritorna azione a Claude
```

### Adapter

```python
class AdapterResult:
    passed: int
    failed: int
    coverage: float
    errors: list[str]
    raw_output: str
```

| Adapter | Runner | Parsing |
|---------|--------|---------|
| `pytest` | `pytest --tb=short -q` | Exit code + stdout |
| `behave` | `behave --format json` | JSON nativo |
| `cucumber` | `cucumber --format json` | JSON nativo |
| `generic` | Qualsiasi comando | Solo exit code |

## Risorse MCP

Leggono dati reali dal DB:

| URI | Contenuto |
|-----|-----------|
| `project://current` | Progetto attivo: nome, path, config |
| `session://current` | Sessione: workflow_type, status, progresso |
| `pipeline://current` | Step con stato, dipendenze, regole |
| `history://sessions` | Sessioni precedenti del progetto |

## Prompts MCP

Template statici + variabili dinamiche (dal DB e dal contesto Claude):

| Prompt | Fase |
|--------|------|
| `bisset/interviewer` | interview |
| `bisset/architect` | design |
| `bisset/analyzer` | analyze |
| `bisset/implementer` | execute |
| `bisset/test-writer` | generate |

### Composizione prompt

Template con variabili `{{...}}`:
- **Variabili DB** (auto): `step.*`, `project.*`, `session.*`
- **Variabili contesto** (da Claude): `context.directory_structure`, `context.patterns`, `context.relevant_files`

Claude chiama `prompt_load("bisset/implementer", context={...})` passando le variabili di contesto. Bisset fonde DB + context e ritorna il prompt composto.

## Loop di convergenza

```
Claude genera codice
    |
Bisset esegue .feature (step_run_tests)
    |
Risultato: 3/5 pass, coverage 60%
    |
Regole DSL: retry (coverage < 80)
    |
Claude riceve feedback strutturato: "scenari X e Y falliti perche' Z"
    |
Claude corregge
    |
Bisset esegue .feature
    |
5/5 pass, coverage 100% -> advance
```

Early stopping: `retries >= 3 -> ask_user`. Se Claude non converge, serve un umano.

## Cosa tenere dal codice attuale

| Componente | Azione |
|-----------|--------|
| `storage.py` | Riscrivere schema, mantenere migration system |
| `app.py` | Riscrivere endpoint, mantenere FastAPI + ResponseWrapper |
| `client.py` | Tenere, aggiornare tool mapping |
| `server.sh` | Tenere (hot reload + color logging gia' fatto) |
| `engine.py` | Riscrivere completamente (rule engine + gate logic) |
| `server.py` | Riscrivere con SDK MCP ufficiale |
| `prompts.py` | Riscrivere come template system |

## Cosa eliminare

- ComplexityAnalyzer / model routing
- 20 file `.agent.md` (specifici per Copilot)
- Catalogo domande hardcoded
- Background jobs / async mode
- Prompt statici per fasi hardcoded
