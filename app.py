"""Small local-only web app. No external hosting or service is required."""

from __future__ import annotations

import json
import importlib.util
import mimetypes
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from urllib.error import URLError
from urllib.parse import urlsplit
from urllib.request import Request, urlopen

from agent import AgentUnavailable, ask_agent
from storage import add_application, add_company, dashboard, set_stale_after_days, update_application

ROOT = Path(__file__).parent
WEB = ROOT / "web"
HOST, PORT = "127.0.0.1", 8765

class Handler(BaseHTTPRequestHandler):
    def _json(self, payload: object, status: int = 200) -> None:
        body = json.dumps(payload, ensure_ascii=False).encode()
        self.send_response(status)
        self.send_header("Content-Type", "application/json; charset=utf-8")
        self.send_header("Content-Length", str(len(body)))
        self.send_header("Cache-Control", "no-store")
        self.end_headers()
        self.wfile.write(body)

    def _body(self) -> dict:
        return json.loads(self.rfile.read(int(self.headers.get("Content-Length", "0"))) or b"{}")

    def do_GET(self) -> None:
        request_path = urlsplit(self.path).path
        if request_path == "/api/dashboard":
            return self._json(dashboard())
        if request_path == "/api/health":
            mcp_installed = importlib.util.find_spec("mcp") is not None
            try:
                with urlopen("http://127.0.0.1:11434/api/tags", timeout=1) as response:
                    installed = json.loads(response.read()).get("models", [])
                # Ollama also lists embedding-only models (for example
                # nomic-embed-text). They cannot answer chat requests or call tools.
                models = [
                    model["name"]
                    for model in installed
                    if not model.get("capabilities")
                    or "completion" in model["capabilities"]
                    or "tools" in model["capabilities"]
                ]
                return self._json({"ollama": True, "models": models, "mcp": mcp_installed})
            except (URLError, TimeoutError, ValueError):
                return self._json({"ollama": False, "models": [], "mcp": mcp_installed})
        relative = "index.html" if request_path == "/" else request_path.lstrip("/")
        path = (WEB / relative).resolve()
        if not path.is_relative_to(WEB.resolve()) or not path.is_file():
            return self._json({"error": "Not found"}, 404)
        content = path.read_bytes()
        self.send_response(200)
        self.send_header("Content-Type", mimetypes.guess_type(path.name)[0] or "application/octet-stream")
        self.send_header("Content-Length", str(len(content)))
        self.send_header("Cache-Control", "no-store")
        self.end_headers()
        self.wfile.write(content)

    def do_POST(self) -> None:
        try:
            payload = self._body()
            if self.path == "/api/companies":
                return self._json(add_company(payload.get("name", ""), payload.get("roles_to_watch", []), payload.get("website", "")), 201)
            if self.path == "/api/applications":
                return self._json(add_application(payload), 201)
            if self.path.startswith("/api/applications/"):
                application_id = self.path.rsplit("/", 1)[-1]
                return self._json(update_application(application_id, payload))
            if self.path == "/api/settings":
                return self._json(set_stale_after_days(int(payload.get("stale_after_days", 14))))
            if self.path == "/api/chat":
                return self._chat(payload)
            return self._json({"error": "Not found"}, 404)
        except (ValueError, KeyError, json.JSONDecodeError) as exc:
            return self._json({"error": str(exc)}, 400)

    def _chat(self, payload: dict) -> None:
        question = str(payload.get("message", "")).strip()
        model = str(payload.get("model", "qwen3:4b")).strip()
        if not question:
            return self._json({"error": "Enter a question first"}, 400)
        try:
            if importlib.util.find_spec("mcp") is None:
                return self._json({"error": "Install project dependencies to enable MCP-powered chat: pip install -r requirements.txt"}, 503)
            return self._json(ask_agent(question, model))
        except AgentUnavailable as exc:
            return self._json({"error": str(exc)}, 503)

    def log_message(self, fmt: str, *args: object) -> None:
        print("[local-app] " + fmt % args)


if __name__ == "__main__":
    print(f"Job Search Assistant running at http://{HOST}:{PORT}")
    ThreadingHTTPServer((HOST, PORT), Handler).serve_forever()
