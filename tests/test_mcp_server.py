from agent.mcp_server import mcp


async def test_mcp_server_exposes_observability_tools():
    names = {tool.name for tool in await mcp.list_tools()}
    assert names == {"metrics", "logs", "traces", "changes", "runbooks"}
