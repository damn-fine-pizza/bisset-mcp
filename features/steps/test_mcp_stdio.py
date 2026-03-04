"""
Step definitions for mcp_server_stdio.feature.

Spawns workflow_server on a free port, then connects mcp_server as a subprocess
via the official MCP Python SDK (StdioServerParameters + ClientSession).
"""
import os
import sys
import time
import threading
import pytest
import anyio
import uvicorn
from pytest_bdd import scenarios, given, when, then, parsers

scenarios('../mcp_server_stdio.feature')

MCP_PORT = 8766


# ── helpers ──────────────────────────────────────────────────────────────────

def _start_real_server(port: int, db: str):
    """Start a real uvicorn workflow_server in a background thread."""
    try:
        os.remove(db)
    except FileNotFoundError:
        pass
    import orchestrator.workflow_server.app as app_module
    from orchestrator.workflow_server.storage import Storage
    from orchestrator.workflow_server.catalog import Catalog
    from orchestrator.workflow_server.renderers import Renderers
    from orchestrator.workflow_server.engine import WorkflowEngine
    storage = Storage(db)
    app_module._storage = storage
    app_module._catalog = Catalog()
    app_module._renderers = Renderers(storage)
    app_module._engine = WorkflowEngine(storage, app_module._catalog, app_module._renderers)

    config = uvicorn.Config(app_module.app, host='127.0.0.1', port=port, log_level='error')
    server = uvicorn.Server(config)
    t = threading.Thread(target=server.run, daemon=True)
    t.start()
    # wait for server to be ready
    import httpx
    for _ in range(30):
        try:
            httpx.get(f'http://127.0.0.1:{port}/health', timeout=1).raise_for_status()
            break
        except Exception:
            time.sleep(0.2)
    return server


# ── fixtures ──────────────────────────────────────────────────────────────────

_server_instance = None
_server_db = '/tmp/bdd_mcp_stdio.db'


@pytest.fixture(scope='module')
def real_workflow_server():
    global _server_instance
    _server_instance = _start_real_server(MCP_PORT, _server_db)
    yield
    _server_instance.should_exit = True


async def _make_mcp_session(port: int):
    from mcp import ClientSession, StdioServerParameters
    from mcp.client.stdio import stdio_client
    params = StdioServerParameters(
        command=sys.executable,
        args=['-m', 'orchestrator.mcp_server'],
        env={**os.environ, 'WORKFLOW_BACKEND_URL': f'http://127.0.0.1:{port}'},
    )
    return params


# ── given ─────────────────────────────────────────────────────────────────────

@given(parsers.parse('the workflow server is running on port {port:d}'), target_fixture='mcp_port')
def wf_running_on_port(real_workflow_server, port):
    return port


@given(parsers.parse('a connected MCP session on port {port:d}'), target_fixture='mcp_session_data')
def connected_session(real_workflow_server, port):
    return {'port': port}


@given('the mcp_server is started as a subprocess')
def mcp_subprocess(mcp_port):
    pass  # spawned inside when/then steps via anyio.run


# ── when ──────────────────────────────────────────────────────────────────────

@when('the MCP client initialises the session', target_fixture='init_result')
def mcp_init(mcp_port):
    async def _run():
        from mcp import ClientSession, StdioServerParameters
        from mcp.client.stdio import stdio_client
        params = StdioServerParameters(
            command=sys.executable,
            args=['-m', 'orchestrator.mcp_server'],
            env={**os.environ, 'WORKFLOW_BACKEND_URL': f'http://127.0.0.1:{mcp_port}'},
        )
        async with stdio_client(params) as (read, write):
            async with ClientSession(read, write) as session:
                result = await session.initialize()
                return {'server_name': result.serverInfo.name if result.serverInfo else 'ok'}
    return anyio.run(_run)


@when('I list the available tools', target_fixture='tools_list')
def list_tools(mcp_session_data):
    async def _run():
        from mcp import ClientSession, StdioServerParameters
        from mcp.client.stdio import stdio_client
        params = StdioServerParameters(
            command=sys.executable,
            args=['-m', 'orchestrator.mcp_server'],
            env={**os.environ, 'WORKFLOW_BACKEND_URL': f'http://127.0.0.1:{mcp_session_data["port"]}'},
        )
        async with stdio_client(params) as (read, write):
            async with ClientSession(read, write) as session:
                await session.initialize()
                result = await session.list_tools()
                return [t.name for t in result.tools]
    return anyio.run(_run)


@when('I list the available resources', target_fixture='resources_list')
def list_resources(mcp_session_data):
    async def _run():
        from mcp import ClientSession, StdioServerParameters
        from mcp.client.stdio import stdio_client
        params = StdioServerParameters(
            command=sys.executable,
            args=['-m', 'orchestrator.mcp_server'],
            env={**os.environ, 'WORKFLOW_BACKEND_URL': f'http://127.0.0.1:{mcp_session_data["port"]}'},
        )
        async with stdio_client(params) as (read, write):
            async with ClientSession(read, write) as session:
                await session.initialize()
                result = await session.list_resources()
                return [str(r.uri) for r in result.resources]
    return anyio.run(_run)


@when('I list the available prompts', target_fixture='prompts_list')
def list_prompts(mcp_session_data):
    async def _run():
        from mcp import ClientSession, StdioServerParameters
        from mcp.client.stdio import stdio_client
        params = StdioServerParameters(
            command=sys.executable,
            args=['-m', 'orchestrator.mcp_server'],
            env={**os.environ, 'WORKFLOW_BACKEND_URL': f'http://127.0.0.1:{mcp_session_data["port"]}'},
        )
        async with stdio_client(params) as (read, write):
            async with ClientSession(read, write) as session:
                await session.initialize()
                result = await session.list_prompts()
                return [p.name for p in result.prompts]
    return anyio.run(_run)


@when(parsers.parse('I call tool "{tool}" with project name "{name}"'), target_fixture='tool_call_result')
def call_tool(mcp_session_data, tool, name):
    async def _run():
        from mcp import ClientSession, StdioServerParameters
        from mcp.client.stdio import stdio_client
        params = StdioServerParameters(
            command=sys.executable,
            args=['-m', 'orchestrator.mcp_server'],
            env={**os.environ, 'WORKFLOW_BACKEND_URL': f'http://127.0.0.1:{mcp_session_data["port"]}'},
        )
        async with stdio_client(params) as (read, write):
            async with ClientSession(read, write) as session:
                await session.initialize()
                result = await session.call_tool(tool, {'project_meta': {'name': name}})
                import json
                content = result.content[0].text if result.content else '{}'
                return json.loads(content)
    return anyio.run(_run)


# ── then ──────────────────────────────────────────────────────────────────────

@then('the server should respond with its capabilities')
def server_responds(init_result):
    assert init_result is not None


@then(parsers.parse('the tools should include "{tool_name}"'))
def tools_include(tools_list, tool_name):
    assert tool_name in tools_list, f'{tool_name!r} not in {tools_list}'


@then(parsers.parse('the resources should include "{uri}"'))
def resources_include(resources_list, uri):
    assert uri in resources_list, f'{uri!r} not in {resources_list}'


@then(parsers.parse('the prompts should include "{prompt_name}"'))
def prompts_include(prompts_list, prompt_name):
    assert prompt_name in prompts_list, f'{prompt_name!r} not in {prompts_list}'


@then(parsers.parse('the result status should be "{status}"'))
def result_status(tool_call_result, status):
    assert tool_call_result.get('status') == status
