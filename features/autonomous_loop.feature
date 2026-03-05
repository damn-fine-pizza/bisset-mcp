Feature: Autonomous Orchestration Tools
  As a Copilot CLI agent in autopilot mode
  I want macro-level tools that encapsulate the workflow loop
  So that I can execute development tasks without micro-managing every step

  Scenario: workflow_status returns full snapshot in one call
    Given I have a session in execution phase with some tasks
    When I call workflow_status
    Then the response includes "phase" equal to "execution"
    And the response includes a "tasks_total" field
    And the response includes "current_task" with an id field

  Scenario: workflow_bootstrap_project detects a Python BDD project
    Given a Python BDD project directory
    When I bootstrap that directory
    Then the detected test_runner is "behave"
    And the detected features_dir is "features"
    And the detected project_path matches the directory

  Scenario: workflow_bootstrap_project detects a Rust project
    Given a Rust project directory
    When I bootstrap that directory
    Then the detected test_runner is "cargo"
    And the detected project_path matches the directory

  Scenario: workflow_bootstrap_project merges into active session
    Given I have an active session with project_path not set
    And a Python BDD project directory
    When I bootstrap that directory into the session
    Then the response merged_into_session is true
    And the session project_meta now contains a project_path

  Scenario: workflow_run_until_blocked returns done when all tasks already done
    Given I have a session where all tasks are pre-accepted
    When I call workflow_run_until_blocked with max_iterations 5
    Then the response status is "done"

  Scenario: workflow_run_until_blocked returns blocked on missing feature file
    Given I have a session in execution phase
    When I call workflow_run_until_blocked with max_iterations 3
    Then the response status is "blocked"
    And the response includes a "fix" field

  Scenario: workflow_get_events returns event log for active session
    Given I have a session with some tool calls recorded
    When I call workflow_get_events with limit 10
    Then the response includes an "events" list
    And each event has "tool" and "timestamp" fields

  Scenario: workflow_bootstrap_project rejects non-existent directory
    When I bootstrap a non-existent directory
    Then the response includes an "error" field
