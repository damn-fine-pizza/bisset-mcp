Feature: Calculator
  The calculator implements basic integer arithmetic.
  These scenarios are the acceptance criteria for the "Implement calculator"
  step: Bisset will not let the step pass until every scenario is green.

  Scenario: Add two numbers
    Given the numbers 7 and 5
    When I add them
    Then the result is 12

  Scenario: Subtract two numbers
    Given the numbers 7 and 5
    When I subtract them
    Then the result is 2
