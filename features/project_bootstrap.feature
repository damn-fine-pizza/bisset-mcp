Feature: Project Specification Bootstrap
  As a User
  I want to provide my project requirements and get all documentation scaffolding done
  So that I can start the execution phase immediately

  Scenario: Complete bootstrap from zero to execution-ready
    Given the workflow server is running
    And I start a new workflow for project "MyApp"
    When I answer all the interview questions
    And I freeze the specification
    Then a specification document should exist
    And an ADR stub should exist
    And a work breakdown should exist
    And the workflow should be in "execution" phase

  Scenario: Bootstrap preserves project metadata
    Given the workflow server is running
    When I start a new workflow for project "BissetMCP"
    Then the workflow state should show phase "interview"
