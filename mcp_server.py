"""Read-only MCP tools for the local job tracker. Run with: python mcp_server.py"""

from datetime import date

from mcp.server import MCPServer

from storage import dashboard, get_follow_up_applications

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
    return [_application_reference(app) for app in applications if not status or app.get("status") == status]


def _application_reference(application: dict) -> dict:
    """Add a stable dashboard link to an application result."""
    return {**application, "tracker_link": f"#applications?application_id={application.get('id', '')}"}


@mcp.tool()
def search_tracker(query: str, status: str = "", limit: int = 20) -> list[dict]:
    """Search saved jobs and applications by company, role, status, location, requirements, notes, and activity text. Results link to the matching tracker entry."""
    terms = [term.casefold() for term in query.split() if term.strip()]
    selected_status = status.strip().casefold()
    results = []
    for application in dashboard()["applications"]:
        if selected_status and application.get("status", "").casefold() != selected_status:
            continue
        searchable = " ".join(str(application.get(key, "")) for key in (
            "company", "role", "status", "location", "url", "source", "work_mode", "salary",
            "requirements", "job_description", "follow_up_date", "next_action", "notes",
        )).casefold()
        searchable += " " + " ".join(str(item.get("note", "")) for item in application.get("activities", [])).casefold()
        if all(term in searchable for term in terms):
            results.append(_application_reference(application))
        if len(results) >= max(1, min(int(limit), 50)):
            break
    return results


@mcp.tool()
def get_application_details(application_id: str) -> dict:
    """Get one saved job's status, follow-up details, activity history, and resume match analysis by its tracker ID."""
    application = next((item for item in dashboard()["applications"] if item.get("id") == application_id), None)
    if application is None:
        return {"error": "No tracker entry has that ID."}
    return _application_reference(application)


@mcp.tool()
def summarize_resume_matches(min_score: int = 0, limit: int = 20) -> list[dict]:
    """Summarize saved jobs' deterministic resume keyword coverage, supported requirements, and gaps. Results link to each tracker entry."""
    results = []
    for application in dashboard()["applications"]:
        analysis = application.get("match_analysis", {})
        score = analysis.get("score")
        if score is not None and score < max(0, min(int(min_score), 100)):
            continue
        results.append({
            "id": application.get("id"), "company": application.get("company"),
            "role": application.get("role"), "status": application.get("status"),
            "score": score, "matched": analysis.get("matched", []), "gaps": analysis.get("gaps", []),
            "explanation": analysis.get("explanation", ""),
            "tracker_link": f"#applications?application_id={application.get('id', '')}",
        })
    ranked = sorted(results, key=lambda item: item.get("score") if item.get("score") is not None else -1, reverse=True)
    return ranked[:max(1, min(int(limit), 50))]


@mcp.tool()
def find_jobs_needing_follow_up() -> list[dict]:
    """Return active jobs with upcoming or overdue scheduled follow-ups, plus stale activity. Results link to each tracker entry."""
    results = {app["id"]: app for app in get_follow_up_applications()}
    today = date.today()
    for application in dashboard()["applications"]:
        if application.get("status") in {"offer", "rejected", "withdrawn"}:
            continue
        try:
            follow_up = date.fromisoformat(application.get("follow_up_date", ""))
        except ValueError:
            continue
        if follow_up > today:
            results[application["id"]] = {
                **application,
                "reminder_type": "upcoming",
                "days_until_follow_up": (follow_up - today).days,
                "reminder_date": follow_up.isoformat(),
            }
    return [_application_reference(app) for app in results.values()]


if __name__ == "__main__":
    mcp.run()
