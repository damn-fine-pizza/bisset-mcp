# Scaffolding Documentazione — BissetMCP

Obiettivo: fornire una struttura e template per la documentazione del progetto in modo che lo Scrum Master (Senior Product Manager) possa assegnare e coordinare il lavoro.

## Struttura cartelle proposta (/docs)
- /docs/overview.md            → panoramica progetto, value proposition, obiettivi
- /docs/api/                   → contratti API
  - api-contract.md
  - endpoints.md
- /docs/agents/                → documentazione per ciascun agente
  - agent-template.md
- /docs/how-to/                → guide di avvio e uso
  - start-local.md
  - docker-compose.md
- /docs/contributing/          → CONTRIBUTING.md, code of conduct
- /docs/architecture-detailed.md

## Template README per componente
- Nome componente
- Scopo
- Endpoints / API
- How to run (local, docker)
- Tests
- Contributing

## Template API contract
- Endpoint
- Metodo
- Request body (schema)
- Response (schema)
- Esempi
- Errori comuni

## Todo operativi (priorità e assegnazioni suggerite)
1. doc-structure-create (priority: high) — Creare le cartelle /docs e file stub (Assegnato: Scrum Master)
2. api-contract-template (priority: high) — Redigere api-contract.md con schema del context e contratti (Assegnato: SW Architect)
3. agents-readme-template (priority: medium) — Creare agent-template.md con formato richiesto per ogni agente (Assegnato: Senior Developer)
4. start-and-docker-guides (priority: high) — Documentare docker-compose e start scripts (Assegnato: DevOps / Senior Developer)
5. contributing-and-coc (priority: medium) — Scrivere CONTRIBUTING.md e CoC (Assegnato: Senior Product Manager)
6. examples-e2e (priority: low) — Aggiungere esempio di sprint run e output (Assegnato: QA Engineer)

## Note per lo Scrum Master
- Predisporre PR template e checklist per la documentazione.
- Coordinare brevi task di 1-2 giorni e assegnare owner per ciascun file.
- Usare il MCP Context Server per tracciare lo stato dei document tasks come task nel context.

