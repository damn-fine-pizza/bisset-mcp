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

  Scenario: Server auto-restores last session on startup
    Given I have answered 3 interview questions
    When the workflow server is restarted
    Then recording a new answer should not crash
    Given the specification has been frozen
    When the workflow server is restarted
    Then the workflow phase should be "execution"

  Scenario: list_sessions includes phase and sub_phase for resume
    Given the specification has been frozen
    And the phase has been advanced to "phase_3_architect"
    When I list all sessions
    Then the session entry should include phase "execution"
    And the session entry should include sub_phase "phase_3_architect"

  Scenario: list_sessions includes task progress for resume
    Given the specification has been frozen
    When I list all sessions
    Then the session entry should include tasks_done 0
    And the session entry should include tasks_total greater than 0

  Scenario: switch_session returns sub_phase directly
    Given the specification has been frozen
    And the phase has been advanced to "phase_3_architect"
    When I switch to the current session
    Then the switch response should include sub_phase "phase_3_architect"
