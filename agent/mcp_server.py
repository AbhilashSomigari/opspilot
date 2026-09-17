from mcp.server.fastmcp import FastMCP

from agent.app.rag.hybrid import hybrid_search
from agent.app.tools.changes import recent_changes
from agent.app.tools.logs import search_logs
from agent.app.tools.metrics import service_metrics
from agent.app.tools.traces import recent_traces

mcp = FastMCP("OpsPilot Observability")

@mcp.tool()
async def metrics(service: str) -> dict:
    """Get request rate, 5xx rate, and p95 latency for a service."""
    return await service_metrics(service)

@mcp.tool()
async def logs(service: str, contains: str = "") -> dict:
    """Search recent structured logs."""
    return await search_logs(service, contains)

@mcp.tool()
async def traces(service: str) -> dict:
    """Get recent distributed traces from Jaeger."""
    return await recent_traces(service)

@mcp.tool()
async def changes(service: str) -> dict:
    """Get recent deployments and GitHub commits."""
    return await recent_changes(service)

@mcp.tool()
def runbooks(query: str) -> list[dict]:
    """Hybrid search over runbooks and previous incidents."""
    return hybrid_search(query)

if __name__ == "__main__":
    mcp.run()
