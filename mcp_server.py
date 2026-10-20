"""Read-only MCP tools for the local job tracker. Run with: python mcp_server.py"""

from mcp.server import MCPServer

from storage import dashboard, get_stale_applications

mcp = MCPServer(
    "Local Job Search Assistant",
    instructions="Read-only tools for inspecting a private local job-search tracker. No tool can modify tracker data.",
)


@mcp.tool()
def list_tracked_companies() -> list[dict]:
    """List companies the user wants to track and roles of interest."""
    return dashboard()["companies"]


@mcp.tool()
def list_applications(status: str = "") -> list[dict]:
    """List saved jobs and applications, optionally filtered by status."""
    applications = dashboard()["applications"]
    return [app for app in applications if not status or app.get("status") == status]


@mcp.tool()
def find_jobs_needing_follow_up() -> list[dict]:
    """Return active jobs with no recorded activity beyond the configured stale threshold."""
    return get_stale_applications()


if __name__ == "__main__":
    mcp.run()
