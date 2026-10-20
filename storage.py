"""Excel-backed persistence and job tracker operations."""

from __future__ import annotations

import json
import os
import threading
import uuid
from datetime import date, datetime, timedelta
from functools import wraps
from pathlib import Path
from typing import Any, Callable, TypeVar

from openpyxl import Workbook, load_workbook
from openpyxl.styles import Alignment, Font, PatternFill

DATA_DIR = Path(__file__).parent / "data"
DATA_FILE = DATA_DIR / "job_tracker.xlsx"
LEGACY_DATA_FILE = DATA_DIR / "job_tracker.json"
TEMP_FILE = DATA_DIR / "job_tracker.tmp.xlsx"
DEFAULTS: dict[str, Any] = {
    "settings": {"stale_after_days": 14},
    "companies": [],
    "applications": [],
    "activities": [],
}
STATUSES = {"watching", "saved", "applied", "screening", "interview", "offer", "rejected", "withdrawn"}
COMPANY_COLUMNS = ("id", "name", "roles_to_watch", "website", "added_date")
APPLICATION_COLUMNS = (
    "id", "company_id", "company", "role", "url", "location", "source", "status",
    "applied_date", "last_activity_date", "follow_up_date", "next_action", "notes", "created_at", "updated_at",
)
ACTIVITY_COLUMNS = ("id", "application_id", "occurred_at", "type", "status", "note")
ACTIVITY_TYPES = {"role_added", "status_change", "note", "recruiter_contact", "interview", "follow_up"}
_LOCK = threading.RLock()
F = TypeVar("F", bound=Callable[..., Any])


def _synchronized(function: F) -> F:
    @wraps(function)
    def wrapper(*args: Any, **kwargs: Any) -> Any:
        with _LOCK:
            return function(*args, **kwargs)
    return wrapper  # type: ignore[return-value]


def _today() -> str:
    return date.today().isoformat()


def _text(value: Any) -> str:
    if value is None:
        return ""
    if isinstance(value, (datetime, date)):
        return value.isoformat()
    return str(value)


def _read_sheet(sheet: Any, columns: tuple[str, ...]) -> list[dict[str, Any]]:
    if sheet.max_row < 1:
        return []
    headers = [_text(cell.value).strip() for cell in sheet[1]]
    positions = {header: index for index, header in enumerate(headers) if header}
    missing = [column for column in columns if column not in positions]
    if missing:
        raise ValueError(f"The {sheet.title} sheet is missing columns: {', '.join(missing)}")
    rows: list[dict[str, Any]] = []
    for values in sheet.iter_rows(min_row=2, values_only=True):
        row = {column: values[positions[column]] if positions[column] < len(values) else None for column in columns}
        if any(value is not None for value in row.values()):
            rows.append(row)
    return rows


def _read_workbook() -> dict[str, Any]:
    try:
        workbook = load_workbook(DATA_FILE, read_only=True, data_only=True)
        required = {"Applications", "Companies", "Settings"}
        missing = required.difference(workbook.sheetnames)
        if missing:
            raise ValueError(f"Tracker workbook is missing sheets: {', '.join(sorted(missing))}")
        companies = _read_sheet(workbook["Companies"], COMPANY_COLUMNS)
        applications = _read_sheet(workbook["Applications"], APPLICATION_COLUMNS)
        activities = _read_sheet(workbook["Activity"], ACTIVITY_COLUMNS) if "Activity" in workbook.sheetnames else []
        settings_sheet = workbook["Settings"]
        settings: dict[str, Any] = {}
        for key, value in settings_sheet.iter_rows(min_row=2, max_col=2, values_only=True):
            if key:
                settings[str(key)] = value
        workbook.close()
    except (OSError, ValueError, KeyError) as exc:
        if isinstance(exc, ValueError) and str(exc).startswith("Tracker workbook"):
            raise
        raise ValueError(f"Could not read {DATA_FILE.name}: {exc}") from exc

    for company in companies:
        company["roles_to_watch"] = [role.strip() for role in _text(company.get("roles_to_watch")).split(";") if role.strip()]
        for key in ("id", "name", "website", "added_date"):
            company[key] = _text(company.get(key))
    for application in applications:
        for key in APPLICATION_COLUMNS:
            application[key] = _text(application.get(key))
    for activity in activities:
        for key in ACTIVITY_COLUMNS:
            activity[key] = _text(activity.get(key))
    settings.setdefault("stale_after_days", DEFAULTS["settings"]["stale_after_days"])
    return {"settings": settings, "companies": companies, "applications": applications, "activities": activities}


def _style_sheet(sheet: Any, columns: tuple[str, ...]) -> None:
    sheet.freeze_panes = "A2"
    sheet.sheet_view.showGridLines = False
    sheet.auto_filter.ref = f"A1:{sheet.cell(row=1, column=len(columns)).coordinate}1"
    for cell in sheet[1]:
        cell.font = Font(bold=True, color="FFFFFF")
        cell.fill = PatternFill("solid", fgColor="315D40")
        cell.alignment = Alignment(vertical="center")
    sheet.row_dimensions[1].height = 24
    for row_number in range(2, sheet.max_row + 1):
        sheet.row_dimensions[row_number].height = 22
    for index, column in enumerate(columns, start=1):
        sheet.column_dimensions[sheet.cell(row=1, column=index).column_letter].width = min(max(len(column) + 3, 15), 34)


def _set_value(cell: Any, value: Any) -> None:
    if isinstance(value, (list, tuple)):
        value = "; ".join(_text(item) for item in value)
    if isinstance(value, str):
        cell.value = value
        # Keep user-entered text such as '=role' as text, never an Excel formula.
        cell.data_type = "s"
    else:
        cell.value = value
    cell.alignment = Alignment(vertical="top", wrap_text=True)


def _write_workbook(data: dict[str, Any]) -> None:
    DATA_DIR.mkdir(parents=True, exist_ok=True)
    workbook = Workbook()
    applications_sheet = workbook.active
    applications_sheet.title = "Applications"
    companies_sheet = workbook.create_sheet("Companies")
    activities_sheet = workbook.create_sheet("Activity")
    settings_sheet = workbook.create_sheet("Settings")

    for sheet, columns in ((applications_sheet, APPLICATION_COLUMNS), (companies_sheet, COMPANY_COLUMNS)):
        sheet.append(columns)
        for row in data["applications"] if sheet is applications_sheet else data["companies"]:
            values = []
            for column in columns:
                value = row.get(column)
                if column == "roles_to_watch":
                    value = "; ".join(row.get(column, []))
                values.append(value)
            sheet.append(values)
        _style_sheet(sheet, columns)
        for row in sheet.iter_rows(min_row=2):
            for cell in row:
                if isinstance(cell.value, str):
                    cell.data_type = "s"
                cell.alignment = Alignment(vertical="top", wrap_text=True)
        if sheet.max_row > 1:
            sheet.auto_filter.ref = f"A1:{sheet.cell(row=sheet.max_row, column=len(columns)).coordinate}"

    activities_sheet.append(ACTIVITY_COLUMNS)
    for activity in data.get("activities", []):
        activities_sheet.append([activity.get(column) for column in ACTIVITY_COLUMNS])
    _style_sheet(activities_sheet, ACTIVITY_COLUMNS)
    for row in activities_sheet.iter_rows(min_row=2):
        for cell in row:
            if isinstance(cell.value, str):
                cell.data_type = "s"
            cell.alignment = Alignment(vertical="top", wrap_text=True)
    for column, width in {"A": 38, "B": 38, "C": 23, "D": 22, "E": 18, "F": 70}.items():
        activities_sheet.column_dimensions[column].width = width
    if activities_sheet.max_row > 1:
        activities_sheet.auto_filter.ref = f"A1:F{activities_sheet.max_row}"

    settings_sheet.append(("setting", "value"))
    for key, value in data["settings"].items():
        settings_sheet.append((key, value))
    _style_sheet(settings_sheet, ("setting", "value"))
    settings_sheet.column_dimensions["A"].width = 24
    settings_sheet.column_dimensions["B"].width = 28
    companies_sheet.column_dimensions["A"].width = 38
    companies_sheet.column_dimensions["B"].width = 30
    companies_sheet.column_dimensions["C"].width = 42
    companies_sheet.column_dimensions["D"].width = 42
    companies_sheet.column_dimensions["E"].width = 16

    try:
        workbook.save(TEMP_FILE)
        workbook.close()
        os.replace(TEMP_FILE, DATA_FILE)
    except PermissionError as exc:
        TEMP_FILE.unlink(missing_ok=True)
        raise ValueError("Could not save the Excel tracker. Close it in Excel and try again.") from exc
    return None


@_synchronized
def load_data() -> dict[str, Any]:
    DATA_DIR.mkdir(parents=True, exist_ok=True)
    if DATA_FILE.exists():
        return _read_workbook()

    # Import the previous local JSON store once, then make Excel authoritative.
    if LEGACY_DATA_FILE.exists():
        try:
            data = json.loads(LEGACY_DATA_FILE.read_text(encoding="utf-8"))
        except (json.JSONDecodeError, OSError) as exc:
            raise ValueError(f"Could not migrate {LEGACY_DATA_FILE.name}: {exc}") from exc
        for key, value in DEFAULTS.items():
            data.setdefault(key, value.copy() if isinstance(value, dict) else list(value))
    else:
        data = {"settings": dict(DEFAULTS["settings"]), "companies": [], "applications": [], "activities": []}
    data.setdefault("activities", [])
    _write_workbook(data)
    return data


@_synchronized
def save_data(data: dict[str, Any]) -> dict[str, Any]:
    _write_workbook(data)
    return data


@_synchronized
def dashboard() -> dict[str, Any]:
    data = load_data()
    apps = data["applications"]
    activity_by_application: dict[str, list[dict[str, Any]]] = {}
    for activity in data.get("activities", []):
        activity_by_application.setdefault(activity.get("application_id", ""), []).append(activity)
    for app in apps:
        app["activities"] = sorted(
            activity_by_application.get(app["id"], []),
            key=lambda activity: activity.get("occurred_at", ""),
            reverse=True,
        )
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


@_synchronized
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


@_synchronized
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
    _record_activity(data, application, "role_added", f"Added to pipeline with status: {status_names_for_log(status)}.")
    save_data(data)
    return application


@_synchronized
def update_application(application_id: str, changes: dict[str, Any]) -> dict[str, Any]:
    data = load_data()
    app = next((a for a in data["applications"] if a["id"] == application_id), None)
    if not app:
        raise ValueError("Application not found")
    previous_status = app.get("status", "")
    allowed = {"status", "url", "location", "source", "applied_date", "last_activity_date", "follow_up_date", "next_action", "notes", "role"}
    for key, value in changes.items():
        if key in allowed:
            if key == "status" and value not in STATUSES:
                raise ValueError(f"Unknown status: {value}")
            app[key] = value
    app["updated_at"] = datetime.now().isoformat(timespec="seconds")
    if app.get("status") != previous_status:
        app["last_activity_date"] = _today()
        _record_activity(data, app, "status_change", f"Status changed from {status_names_for_log(previous_status)} to {status_names_for_log(app['status'])}.")
    save_data(data)
    return app


def status_names_for_log(status: str) -> str:
    return str(status or "Unknown").replace("_", " ").capitalize()


def _record_activity(data: dict[str, Any], app: dict[str, Any], activity_type: str, note: str) -> dict[str, Any]:
    activity = {
        "id": str(uuid.uuid4()),
        "application_id": app["id"],
        "occurred_at": datetime.now().isoformat(timespec="seconds"),
        "type": activity_type,
        "status": app.get("status", ""),
        "note": note.strip(),
    }
    data.setdefault("activities", []).append(activity)
    return activity


@_synchronized
def log_application_activity(application_id: str, activity_type: str, note: str) -> dict[str, Any]:
    activity_type = activity_type.strip().lower()
    note = note.strip()
    if activity_type not in ACTIVITY_TYPES - {"role_added", "status_change"}:
        raise ValueError("Choose a valid activity type")
    if not note:
        raise ValueError("Add a note before logging this activity")
    data = load_data()
    app = next((item for item in data["applications"] if item["id"] == application_id), None)
    if not app:
        raise ValueError("Application not found")
    activity = _record_activity(data, app, activity_type, note)
    app["last_activity_date"] = _today()
    app["updated_at"] = datetime.now().isoformat(timespec="seconds")
    save_data(data)
    return activity


@_synchronized
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


@_synchronized
def set_stale_after_days(days: int) -> dict[str, Any]:
    if days < 1 or days > 365:
        raise ValueError("Stale threshold must be between 1 and 365 days")
    data = load_data()
    data["settings"]["stale_after_days"] = days
    return save_data(data)["settings"]
