Feature: Error Handling and Input Validation
  As a User
  I want clear error messages when I do something wrong
  So that I can correct my actions without guessing

  Scenario: Requesting next task before freezing spec returns an error
    Given I have started a new workflow
    When I request the next task
    Then the response should contain an error
    And the error should mention "not in execution phase"

  Scenario: Recording answer for a non-existent question is silently ignored
    Given I have started a new workflow
    When I answer question "q-999" with "invalid"
    Then no error should be raised

  Scenario: Freezing with no answers produces UNANSWERED fields
    Given I have started a new workflow with no answers
    When I freeze the specification
    Then the specification should contain "UNANSWERED" for all fields
