"""MCP tools for the local job tracker. Run with: python mcp_server.py"""

from mcp.server.fastmcp import FastMCP

from storage import add_application, add_company, dashboard, get_stale_applications, update_application

mcp = FastMCP("Local Job Search Assistant")


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
def track_company(name: str, roles_to_watch: list[str] | None = None, website: str = "") -> dict:
    """Add a company to the local watch list."""
    return add_company(name, roles_to_watch, website)


@mcp.tool()
def save_job(company: str, role: str, url: str = "", status: str = "saved", location: str = "", source: str = "", notes: str = "") -> dict:
    """Save a job listing or application in the local tracker."""
    return add_application({"company": company, "role": role, "url": url, "status": status, "location": location, "source": source, "notes": notes})


@mcp.tool()
def update_job(application_id: str, status: str = "", last_activity_date: str = "", follow_up_date: str = "", next_action: str = "", notes: str = "") -> dict:
    """Update status, activity, follow-up, next action, or notes for one saved job."""
    changes = {k: v for k, v in {"status": status, "last_activity_date": last_activity_date, "follow_up_date": follow_up_date, "next_action": next_action, "notes": notes}.items() if v}
    return update_application(application_id, changes)


@mcp.tool()
def find_jobs_needing_follow_up() -> list[dict]:
    """Return active jobs with no recorded activity beyond the configured stale threshold."""
    return get_stale_applications()


if __name__ == "__main__":
    mcp.run()
