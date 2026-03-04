Skeleton per orchestrator e agenti (webhook push + Temporal concept). Avviare con docker-compose in questa cartella.

Servizi inclusi:
- mcp (usa la cartella ../mcp-example)
- orchestrator (dispatch HTTP -> agent webhooks)
- agent-<role> (8 agenti, ognuno espone /webhook)

Comandi rapidi:
- cd orchestrator
- docker-compose up -d --build
- Verifiche: curl http://localhost:8080/dispatch -X POST -H 'Content-Type: application/json' -d '{"agent":"sw-architect","task":{"id":"t1","action":"review-arch"}}'

Nota: Temporal è menzionato come orchestrator concettuale nella discussione; questa composizione usa webhooks push per semplicità locale. Per integrazione con Temporal, vedere la documentazione di Temporal.
