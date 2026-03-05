# Deterministic question and task catalog

QUESTIONS = [
    ("q-001", "What is the project name?"),
    ("q-002", "Who are the primary users (persona)?"),
    ("q-003", "What are the top 3 product goals?"),
    ("q-004", "What are the key constraints (languages, runtimes, licences)?"),
    ("q-005", "What are non-goals for this project?"),
    ("q-006", "What is the expected deployment environment (cloud/on-prem)?"),
    ("q-007", "What CI/CD and testing expectations exist?"),
    ("q-008", "Are there security or compliance constraints?"),
    ("q-009", "What external integrations are required (third-party APIs, databases, message queues, external services)?"),
    ("q-010", "What are the performance and SLA requirements (expected load, p99 latency targets, uptime/availability)?"),
    ("q-011", "What are the core domain entities and their relationships (key data models the system must manage)?"),
    ("q-012", "What is the authentication and authorisation model (who can access what, and how)?"),
    ("q-013", "Is this greenfield or brownfield? If brownfield, describe the existing codebase, tech stack, and constraints."),
    ("q-014", "What are the observability requirements (logging format, metrics, alerting, tracing)?"),
    ("q-015", "What are the data privacy and retention requirements (GDPR, PII handling, data lifecycle)?"),
    ("q-016", "What is the external interface surface (REST API, CLI, GraphQL, SDK, web UI — which and for whom)?"),
]

# Simple default plan template converted into tasks
PLAN_TASKS = [
    ("t-001", "Create project skeleton and CI"),
    ("t-002", "Implement core data models and persistence"),
    ("t-003", "Implement API endpoints and interfaces"),
    ("t-004", "Write unit and integration tests"),
    ("t-005", "Create ADRs and documentation"),
    ("t-006", "Prepare deployment manifests and CI/CD"),
]

class Catalog:
    def questions(self):
        return QUESTIONS

    def default_tasks(self):
        return PLAN_TASKS
