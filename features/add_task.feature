Feature: Add Project-Specific Task
  As a User
  I want to add tasks tailored to my project after freezing the spec
  So that Copilot receives actionable, BDD-verified implementation steps

  Scenario: Add a task with title only
    Given the specification has been frozen
    When I add a task with id "custom-001" and title "Wire stats pipeline"
    Then the task list should contain "custom-001"

  Scenario: Add a task with acceptance criteria
    Given the specification has been frozen
    When I add a task with id "custom-002" and title "Stats overlay" and acceptance criteria "Given the player is playing\nWhen one second elapses\nThen DebugOverlay shows fps > 0"
    Then the task list should contain "custom-002"
    And the task "custom-002" should have acceptance_criteria set

  Scenario: Added task appears as pending next task
    Given the specification has been frozen
    And all default tasks are accepted
    When I add a task with id "custom-003" and title "Extra feature"
    And I request the next task
    Then the task id should be "custom-003"

  Scenario: workflow_add_task requires an active session
    Given no session is active
    When I add a task with id "orphan-001" and title "No session task"
    Then an error should be returned
