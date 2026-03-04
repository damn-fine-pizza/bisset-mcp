Feature: Backend Reload Without Data Loss
  As a User
  I want my workflow state to survive a backend restart
  So that I can reload the server without losing progress

  Scenario: Interview progress survives server restart
    Given I have answered 3 interview questions
    When the workflow server is restarted
    And I request the next question
    Then the question id should be "q-004"

  Scenario: Execution progress survives server restart
    Given the specification has been frozen
    And I have accepted tasks "t-001" and "t-002"
    When the workflow server is restarted
    And I request the next task
    Then the task id should be "t-003"

  Scenario: Phase is correctly restored after restart
    Given the specification has been frozen
    When the workflow server is restarted
    Then the workflow phase should be "execution"
