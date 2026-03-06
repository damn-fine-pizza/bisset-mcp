"""Test Claude MCP Server implementation."""
import pytest
from orchestrator.mcp_server.server import ClaudeServerProtocol


class TestClaudeServerProtocol:
    """Test MCP protocol implementation."""

    @pytest.fixture
    def protocol(self):
        """Create protocol instance."""
        return ClaudeServerProtocol()

    def test_initialize(self, protocol):
        """Test initialize request."""
        request = {'method': 'initialize', 'id': '1'}
        response = protocol.handle_request(request)
        
        assert response['jsonrpc'] == '2.0'
        assert response['result']['serverInfo']['name'] == 'BissetMCP Claude Orchestrator'
        assert response['result']['serverInfo']['version'] == '1.0.0'

    def test_tools_list(self, protocol):
        """Test tools/list."""
        request = {'method': 'tools/list', 'id': '2'}
        response = protocol.handle_request(request)
        
        tools = response['result']['tools']
        assert len(tools) >= 23, "Should have 23+ tools"
        
        tool_names = {t['name'] for t in tools}
        assert 'workflow_new_session' in tool_names
        assert 'workflow_next_task' in tool_names
        assert 'workflow_run_tests' in tool_names

    def test_prompts_list(self, protocol):
        """Test prompts/list."""
        request = {'method': 'prompts/list', 'id': '3'}
        response = protocol.handle_request(request)
        
        prompts = response['result']['prompts']
        assert len(prompts) >= 8
        
        names = {p['name'] for p in prompts}
        assert 'phases/requirements_interview' in names

    def test_resources_list(self, protocol):
        """Test resources/list."""
        request = {'method': 'resources/list', 'id': '4'}
        response = protocol.handle_request(request)
        
        resources = response['result']['resources']
        assert len(resources) >= 4
        
        uris = {r['uri'] for r in resources}
        assert 'spec://current' in uris

    def test_invalid_method(self, protocol):
        """Test error for unknown method."""
        request = {'method': 'unknown', 'id': '5'}
        response = protocol.handle_request(request)
        
        assert 'error' in response
        assert response['error']['code'] == -32000

