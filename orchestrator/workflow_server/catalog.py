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
