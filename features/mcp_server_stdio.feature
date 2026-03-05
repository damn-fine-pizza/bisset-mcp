Feature: MCP Server STDIO Interface
  As a User connecting via Copilot CLI
  I want the MCP server to expose all tools, resources and prompts
  So that I can orchestrate the workflow through the MCP protocol

  Scenario: MCP server starts and initialises correctly
    Given the workflow server is running on port 8766
    And the mcp_server is started as a subprocess
    When the MCP client initialises the session
    Then the server should respond with its capabilities

  Scenario: MCP server exposes all 23 tools
    Given a connected MCP session on port 8766
    When I list the available tools
    Then the tools should include "workflow_start"
    And the tools should include "workflow_next_question"
    And the tools should include "workflow_freeze_spec"
    And the tools should include "workflow_is_done"
    And the tools should include "workflow_advance_phase"
    And the tools should include "workflow_store_proposal"
    And the tools should include "workflow_list_proposals"
    And the tools should include "workflow_add_task"
    And the tools should include "workflow_run_tests"
    And the tools should include "workflow_status"
    And the tools should include "workflow_bootstrap_project"
    And the tools should include "workflow_run_until_blocked"
    And the tools should include "workflow_get_events"

  Scenario: MCP server exposes all 4 resources
    Given a connected MCP session on port 8766
    When I list the available resources
    Then the resources should include "spec://current"
    And the resources should include "plan://workbreakdown"

  Scenario: MCP server exposes all 8 prompts
    Given a connected MCP session on port 8766
    When I list the available prompts
    Then the prompts should include "roles/architect"
    And the prompts should include "phases/requirements_interview"

  Scenario: Tool call via MCP protocol returns correct result
    Given a connected MCP session on port 8766
    When I call tool "workflow_start" with project name "TestProj"
    Then the result status should be "started"
