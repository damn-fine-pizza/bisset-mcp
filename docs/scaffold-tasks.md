# Documentation Scaffolding — BissetMCP

Objective: provide a structure and templates for the project documentation so that the Scrum Master (Senior Product Manager) can assign and coordinate the work.

## Proposed folder structure (/docs)
- /docs/overview.md            → project overview, value proposition, objectives
- /docs/api/                   → API contracts
  - api-contract.md
  - endpoints.md
- /docs/agents/                → documentation for each agent
  - agent-template.md
- /docs/how-to/                → startup and usage guides
  - start-local.md
  - docker-compose.md
- /docs/contributing/          → CONTRIBUTING.md, code of conduct
- /docs/architecture-detailed.md

## Component README Template
- Component name
- Purpose
- Endpoints / API
- How to run (local, docker)
- Tests
- Contributing

## API Contract Template
- Endpoint
- Method
- Request body (schema)
- Response (schema)
- Examples
- Common errors

## Operational Todos (suggested priorities and assignments)
1. doc-structure-create (priority: high) — Create /docs folders and stub files (Assigned: Scrum Master)
2. api-contract-template (priority: high) — Draft api-contract.md with context schema and contracts (Assigned: SW Architect)
3. agents-readme-template (priority: medium) — Create agent-template.md with the required format for each agent (Assigned: Senior Developer)
4. start-and-docker-guides (priority: high) — Document docker-compose and start scripts (Assigned: DevOps / Senior Developer)
5. contributing-and-coc (priority: medium) — Write CONTRIBUTING.md and CoC (Assigned: Senior Product Manager)
6. examples-e2e (priority: low) — Add example of a sprint run and output (Assigned: QA Engineer)

## Notes for the Scrum Master
- Set up a PR template and checklist for documentation.
- Coordinate short 1-2 day tasks and assign an owner for each file.
- Use the MCP Context Server to track the status of document tasks as tasks in the context.
