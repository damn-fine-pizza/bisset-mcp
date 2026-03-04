Feature: Execution Loop
  As a User
  I want to execute tasks one at a time with evidence
  So that the project is built incrementally and traceably

  Scenario: First task returned is always t-001
    Given the specification has been frozen
    When I request the next task
    Then the task id should be "t-001"
    And the task title should be "Create project skeleton and CI"

  Scenario: Accepting a task advances to the next one
    Given the specification has been frozen
    And I have accepted task "t-001" with summary "skeleton done"
    When I request the next task
    Then the task id should be "t-002"

  Scenario: Task result stores evidence
    Given the specification has been frozen
    When I accept task "t-001" with summary "skeleton done" and artifact "pyproject.toml"
    Then the evidence for task "t-001" should be stored

  Scenario: Completing all tasks marks workflow as done
    Given the specification has been frozen
    When I accept all 6 tasks
    Then the workflow should be done

  Scenario: Next task in done phase returns done signal
    Given all tasks have been completed
    When I request the next task
    Then the response should indicate all tasks are done
