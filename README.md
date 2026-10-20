# Local Job Search Assistant

A private, local-first job application tracker with an Ollama agent connected to read-only MCP tools. Your tracker lives on your machine in `data/job_tracker.xlsx` and is excluded from Git.

## Run locally

1. Install Python 3.11 or newer.
2. Create and activate a virtual environment.
3. Install dependencies: `pip install -r requirements.txt`
4. (Optional, for AI chat) Install [Ollama](https://ollama.com), start it, and pull a model such as `ollama pull qwen3:4b`.
5. Start the app: `python app.py`
6. Open <http://127.0.0.1:8765>.

The tracker works without Ollama. AI chat is optional and sends prompts only to the Ollama service configured on your own computer. No account or cloud API key is required.

## What it tracks

- Companies you want to follow, their career portal links, and roles you are interested in
- Applications, URLs, statuses, applied dates, and latest activity
- Follow-up dates, next actions, and private notes
- Stale applications with no recorded activity for 14 days (configurable in Settings)

## MCP tools

Run `python mcp_server.py` to expose tracker reads as MCP tools over stdio. The in-app copilot discovers those tools, passes them to Ollama for tool selection, executes the selected read-only MCP calls, and shows which tools it used. The model cannot save or modify tracker data through MCP. Changes remain explicit actions in the dashboard.

## Local data and backups

The Excel workbook is created automatically on first run. If `data/job_tracker.json` exists from an older version, the app imports its records into the workbook the first time it starts; the JSON file is left in place as a backup. You can edit `data/job_tracker.xlsx` while the app is stopped, or back it up by copying that file. Do not commit it: local tracker files are ignored by Git.

The workbook has `Applications`, `Companies`, `Settings`, and `Activity` sheets. The `Companies` sheet's `website` column stores each company's careers portal URL, which appears as a **Careers** link in the watchlist. Each role's timeline is stored in `Activity`; the app creates dated entries for new roles and status changes, and lets you log recruiter contacts, interviews, follow-ups, and notes. Older workbooks without this sheet are upgraded the next time the app saves data. In **Settings**, download an Excel backup or import a tracker workbook; importing replaces the current tracker after confirmation. Keep the header rows intact. Close the workbook in Excel before changing tracker data in the app so there is no conflict between unsaved spreadsheet edits and app updates.
