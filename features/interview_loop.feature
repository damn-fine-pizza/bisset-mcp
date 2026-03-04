Feature: Requirements Interview Loop
  As a User
  I want to be asked questions one at a time
  So that I can provide structured requirements without being overwhelmed

  Scenario: First question is always about project name
    Given I have started a new workflow
    When I request the next question
    Then the question id should be "q-001"
    And the question text should contain "project name"

  Scenario: Questions are returned in deterministic order
    Given I have started a new workflow
    When I answer question "q-001" with "MyApp"
    And I request the next question
    Then the question id should be "q-002"

  Scenario: Answering all questions signals completion
    Given I have started a new workflow
    When I answer all 8 interview questions
    And I request the next question
    Then the response should indicate all questions are done

  Scenario: Re-answering a question overwrites the previous answer
    Given I have started a new workflow
    And I have answered question "q-001" with "OldName"
    When I answer question "q-001" with "NewName"
    Then the stored answer for "q-001" should be "NewName"
