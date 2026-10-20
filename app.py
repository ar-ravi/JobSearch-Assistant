"""Small local-only web app. No external hosting or service is required."""

from __future__ import annotations

import json
import mimetypes
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from urllib.error import URLError
from urllib.request import Request, urlopen

from storage import add_application, add_company, dashboard, set_stale_after_days, update_application

ROOT = Path(__file__).parent
WEB = ROOT / "web"
HOST, PORT = "127.0.0.1", 8765
OLLAMA_URL = "http://127.0.0.1:11434/api/chat"


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
        if self.path == "/api/dashboard":
            return self._json(dashboard())
        if self.path == "/api/health":
            try:
                with urlopen("http://127.0.0.1:11434/api/tags", timeout=1) as response:
                    models = json.loads(response.read()).get("models", [])
                return self._json({"ollama": True, "models": [m["name"] for m in models]})
            except (URLError, TimeoutError, ValueError):
                return self._json({"ollama": False, "models": []})
        relative = "index.html" if self.path == "/" else self.path.lstrip("/")
        path = (WEB / relative).resolve()
        if not path.is_relative_to(WEB.resolve()) or not path.is_file():
            return self._json({"error": "Not found"}, 404)
        content = path.read_bytes()
        self.send_response(200)
        self.send_header("Content-Type", mimetypes.guess_type(path.name)[0] or "application/octet-stream")
        self.send_header("Content-Length", str(len(content)))
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
        overview = dashboard()
        system = (
            "You are a private job-search assistant. Use only the supplied local tracker data. "
            "Do not invent application facts. Recommend follow-ups based on dates and clearly label suggestions. "
            "Never claim to submit applications or contact recruiters.\n\n"
            f"Tracker data: {json.dumps(overview, ensure_ascii=False)}"
        )
        request = Request(OLLAMA_URL, data=json.dumps({"model": model, "stream": False, "messages": [{"role": "system", "content": system}, {"role": "user", "content": question}]}).encode(), headers={"Content-Type": "application/json"}, method="POST")
        try:
            with urlopen(request, timeout=120) as response:
                result = json.loads(response.read())
            return self._json({"reply": result.get("message", {}).get("content", ""), "model": model})
        except URLError as exc:
            return self._json({"error": "Could not reach Ollama. Start Ollama locally and pull a model first."}, 503)
        except TimeoutError:
            return self._json({"error": "The local model took too long to respond."}, 504)

    def log_message(self, fmt: str, *args: object) -> None:
        print("[local-app] " + fmt % args)


if __name__ == "__main__":
    print(f"Job Search Assistant running at http://{HOST}:{PORT}")
    ThreadingHTTPServer((HOST, PORT), Handler).serve_forever()
