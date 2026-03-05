Feature: Full Workflow End-to-End
  As a Bisset operator
  I want to run the complete workflow from zero to done
  So that all phase transitions and state mutations are consistent end-to-end

  Scenario: Complete phase chain from session start to done
    Given a fresh session is created
    And all interview questions are answered
    And the spec is frozen
    Then the state should show sub_phase "phase_2_5_requirements"
    When I call advance_phase "requirements_valid"
    Then the state should show sub_phase "phase_3_architect"
    When I call advance_phase "tasks_ready"
    Then the state should show sub_phase "phase_4_gherkin"
    When I call advance_phase "features_written"
    Then the state should show sub_phase "phase_5_implement"
    When I call advance_phase "implementation_complete"
    Then the state should show sub_phase "phase_6_coverage"
    When I call advance_phase "coverage_passed"
    Then the state should show sub_phase "done"
    And the phase should be "done"
    And the workflow should be done

  Scenario: Requirements incomplete loop returns to interview then back to validation
    Given a fresh session is created
    And all interview questions are answered
    And the spec is frozen
    When I call advance_phase "requirements_incomplete"
    Then the state should show sub_phase "phase_2_interview"
    When I call advance_phase "interview_updated"
    Then the state should show sub_phase "phase_2_5_requirements"

  Scenario: coverage_failed loops back to implementation
    Given a fresh session is created
    And all interview questions are answered
    And the spec is frozen
    And sub_phase is advanced to "phase_6_coverage"
    When I call advance_phase "coverage_failed"
    Then the state should show sub_phase "phase_5_implement"
    And the phase should be "execution"

  Scenario: State is fully preserved across engine re-init
    Given a fresh session is created
    And all interview questions are answered
    And the spec is frozen
    When I call advance_phase "requirements_valid"
    And the engine is reinitialised from the same database
    Then the state should show sub_phase "phase_3_architect"
