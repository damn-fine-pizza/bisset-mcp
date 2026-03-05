Feature: Workflow Phase Tracking
  As a Bisset sub-agent
  I want to advance and read the workflow sub-phase
  So that the dispatcher can route deterministically without parsing text

  Background:
    Given the specification has been frozen

  Scenario: freeze_spec sets sub_phase to phase_2_5_requirements
    Then the state should show sub_phase "phase_2_5_requirements"

  Scenario: advance_phase transitions sub_phase correctly
    When I advance the phase with signal "requirements_valid"
    Then the state should show sub_phase "phase_3_architect"

  Scenario: advance_phase rejects unknown signals
    When I advance the phase with signal "bogus_signal"
    Then an error should be returned

  Scenario: advance_phase rejects transitions from wrong sub_phase
    When I advance the phase with signal "tasks_ready"
    Then an error should be returned

  Scenario: advance_phase response includes new sub_phase
    When I advance the phase with signal "requirements_valid"
    Then the advance response should contain sub_phase "phase_3_architect"

  Scenario: full phase chain from 2.5 to done
    When I advance through all phases to done
    Then the phase should be "done"
    And the state should show sub_phase "done"

  Scenario: coverage_failed loops back to phase_5_implement
    Given sub_phase is phase_6_coverage
    When I advance the phase with signal "coverage_failed"
    Then the state should show sub_phase "phase_5_implement"

  Scenario: coverage_passed transitions phase to done
    Given sub_phase is phase_6_coverage
    When I advance the phase with signal "coverage_passed"
    Then the phase should be "done"
