Feature: Freeze Specification
  As a User
  I want to lock my answers into a formal specification
  So that the project artifacts are generated and I can start building

  Scenario: Freeze generates the specification document
    Given I have answered all interview questions
    When I freeze the specification
    Then the file "spec_current.md" should exist
    And it should contain my answers

  Scenario: Freeze generates an ADR stub
    Given I have answered all interview questions
    When I freeze the specification
    Then the file "decisions/adr-0001.md" should exist
    And it should have status "Proposed"

  Scenario: Freeze generates a work breakdown
    Given I have answered all interview questions
    When I freeze the specification
    Then the file "plan/workbreakdown.yaml" should exist
    And it should contain the default tasks

  Scenario: Freeze transitions phase to execution
    Given I have answered all interview questions
    When I freeze the specification
    Then the workflow phase should be "execution"

  Scenario: Freeze is idempotent
    Given I have already frozen the specification
    When I freeze the specification again
    Then the workflow phase should still be "execution"
    And no error should be returned

  Scenario: Freeze is blocked when project_path is not set
    Given I have answered all interview questions without project_path
    When I freeze the specification
    Then an error field "error" with value "project_path not set" should be returned
    And the workflow phase should remain "interview"
