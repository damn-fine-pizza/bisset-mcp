Feature: Architecture Proposals
  As bisset-architect
  I want to persist and retrieve architecture proposals from the session DB
  So that proposals survive context interruptions and can be scored in one place

  Background:
    Given the specification has been frozen

  Scenario: store a single proposal and retrieve it
    When I store a proposal with paradigm "oop" and content "## OOP Proposal\nClass diagram here"
    And I list proposals
    Then the proposals list should contain 1 entries
    And the proposal paradigm should be "oop"

  Scenario: proposals content is preserved exactly
    When I store a proposal with paradigm "functional" and content "## FP Proposal\nPipeline here"
    And I list proposals
    Then the proposal content for "functional" should contain "Pipeline here"

  Scenario: all three paradigms can be stored and listed
    When I store a proposal with paradigm "oop" and content "OOP content"
    And I store a proposal with paradigm "functional" and content "FP content"
    And I store a proposal with paradigm "data-oriented" and content "DOD content"
    And I list proposals
    Then the proposals list should contain 3 entries

  Scenario: list proposals returns empty list before any are stored
    When I list proposals
    Then the proposals list should contain 0 entries

  Scenario: store_proposal requires active session
    Given no session is active
    When I store a proposal with paradigm "oop" and content "anything"
    Then an error should be returned
