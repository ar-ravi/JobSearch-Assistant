# Local Job Search Assistant

A private, local-first job application tracker with a local Ollama assistant and MCP tools. Your tracker lives on your machine in `data/job_tracker.json` and is excluded from Git.

## Run locally

1. Install Python 3.11 or newer.
2. Create and activate a virtual environment.
3. Install dependencies: `pip install -r requirements.txt`
4. (Optional, for AI chat) Install [Ollama](https://ollama.com), start it, and pull a model such as `ollama pull qwen3:4b`.
5. Start the app: `python app.py`
6. Open <http://127.0.0.1:8765>.

The tracker works without Ollama. AI chat is optional and sends prompts only to the Ollama service configured on your own computer. No account or cloud API key is required.

## What it tracks

- Companies you want to follow and roles you are interested in
- Applications, URLs, statuses, applied dates, and latest activity
- Follow-up dates, next actions, and private notes
- Stale applications with no recorded activity for 14 days (configurable in Settings)

## MCP tools

Run `python mcp_server.py` to expose the same local tracker operations as MCP tools over stdio. Tools include listing companies/applications, adding or updating an application, and finding stale applications. The MCP process reads and writes the same ignored local JSON file as the dashboard.

## Local data and backups

The data file is created automatically on first run. You can edit `data/job_tracker.json` while the app is stopped, or back it up by copying that file. Do not commit it: the data folder is ignored by Git.
