"""Local JSON persistence and job tracker operations shared by the UI and MCP server."""

from __future__ import annotations

import json
import os
import uuid
from datetime import date, datetime, timedelta
from pathlib import Path
from typing import Any

DATA_DIR = Path(__file__).parent / "data"
DATA_FILE = DATA_DIR / "job_tracker.json"
DEFAULTS: dict[str, Any] = {
    "settings": {"stale_after_days": 14},
    "companies": [],
    "applications": [],
}
STATUSES = {"watching", "saved", "applied", "screening", "interview", "offer", "rejected", "withdrawn"}


def _today() -> str:
    return date.today().isoformat()


def load_data() -> dict[str, Any]:
    DATA_DIR.mkdir(parents=True, exist_ok=True)
    if not DATA_FILE.exists():
        save_data(DEFAULTS)
    try:
        data = json.loads(DATA_FILE.read_text(encoding="utf-8"))
    except (json.JSONDecodeError, OSError) as exc:
        raise ValueError(f"Could not read {DATA_FILE.name}: {exc}") from exc
    for key, value in DEFAULTS.items():
        data.setdefault(key, value.copy() if isinstance(value, dict) else list(value))
    return data


def save_data(data: dict[str, Any]) -> dict[str, Any]:
    DATA_DIR.mkdir(parents=True, exist_ok=True)
    tmp = DATA_FILE.with_suffix(".json.tmp")
    tmp.write_text(json.dumps(data, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
    os.replace(tmp, DATA_FILE)
    return data


def dashboard() -> dict[str, Any]:
    data = load_data()
    apps = data["applications"]
    stale = get_stale_applications()
    active = [a for a in apps if a.get("status") not in {"offer", "rejected", "withdrawn"}]
    return {
        "companies": data["companies"],
        "applications": sorted(apps, key=lambda a: a.get("updated_at", ""), reverse=True),
        "stats": {
            "active": len(active),
            "interviews": sum(a.get("status") == "interview" for a in apps),
            "offers": sum(a.get("status") == "offer" for a in apps),
            "needs_follow_up": len(stale),
        },
        "stale": stale,
        "settings": data["settings"],
    }


def add_company(name: str, roles_to_watch: list[str] | None = None, website: str = "") -> dict[str, Any]:
    name = name.strip()
    if not name:
        raise ValueError("Company name is required")
    data = load_data()
    existing = next((c for c in data["companies"] if c["name"].casefold() == name.casefold()), None)
    if existing:
        return existing
    company = {"id": str(uuid.uuid4()), "name": name, "roles_to_watch": roles_to_watch or [], "website": website.strip(), "added_date": _today()}
    data["companies"].append(company)
    save_data(data)
    return company


def add_application(payload: dict[str, Any]) -> dict[str, Any]:
    company_name = str(payload.get("company", "")).strip()
    role = str(payload.get("role", "")).strip()
    if not company_name or not role:
        raise ValueError("Company and role are required")
    status = str(payload.get("status", "saved")).lower()
    if status not in STATUSES:
        raise ValueError(f"Status must be one of: {', '.join(sorted(STATUSES))}")
    data = load_data()
    company = next((c for c in data["companies"] if c["name"].casefold() == company_name.casefold()), None)
    if not company:
        company = add_company(company_name)
        data = load_data()
    today = _today()
    application = {
        "id": str(uuid.uuid4()), "company_id": company["id"], "company": company["name"], "role": role,
        "url": str(payload.get("url", "")).strip(), "location": str(payload.get("location", "")).strip(),
        "source": str(payload.get("source", "")).strip(), "status": status,
        "applied_date": str(payload.get("applied_date", today if status not in {"watching", "saved"} else "")),
        "last_activity_date": str(payload.get("last_activity_date", today)),
        "follow_up_date": str(payload.get("follow_up_date", "")),
        "next_action": str(payload.get("next_action", "")).strip(), "notes": str(payload.get("notes", "")).strip(),
        "created_at": datetime.now().isoformat(timespec="seconds"), "updated_at": datetime.now().isoformat(timespec="seconds"),
    }
    data["applications"].append(application)
    save_data(data)
    return application


def update_application(application_id: str, changes: dict[str, Any]) -> dict[str, Any]:
    data = load_data()
    app = next((a for a in data["applications"] if a["id"] == application_id), None)
    if not app:
        raise ValueError("Application not found")
    allowed = {"status", "url", "location", "source", "applied_date", "last_activity_date", "follow_up_date", "next_action", "notes", "role"}
    for key, value in changes.items():
        if key in allowed:
            if key == "status" and value not in STATUSES:
                raise ValueError(f"Unknown status: {value}")
            app[key] = value
    app["updated_at"] = datetime.now().isoformat(timespec="seconds")
    save_data(data)
    return app


def get_stale_applications() -> list[dict[str, Any]]:
    data = load_data()
    threshold = int(data["settings"].get("stale_after_days", 14))
    cutoff = date.today() - timedelta(days=threshold)
    stale = []
    for app in data["applications"]:
        if app.get("status") in {"offer", "rejected", "withdrawn"}:
            continue
        reference = app.get("last_activity_date") or app.get("applied_date")
        if not reference:
            continue
        try:
            activity_date = date.fromisoformat(reference)
        except ValueError:
            continue
        days = (date.today() - activity_date).days
        if activity_date <= cutoff:
            stale.append({**app, "days_since_activity": days})
    return sorted(stale, key=lambda a: a["days_since_activity"], reverse=True)


def set_stale_after_days(days: int) -> dict[str, Any]:
    if days < 1 or days > 365:
        raise ValueError("Stale threshold must be between 1 and 365 days")
    data = load_data()
    data["settings"]["stale_after_days"] = days
    return save_data(data)["settings"]
