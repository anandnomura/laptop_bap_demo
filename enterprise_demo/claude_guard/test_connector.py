from __future__ import annotations

import argparse
import json
from datetime import datetime, timezone
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from typing import Any
from urllib.parse import urlparse


HOST = "127.0.0.1"
PORT = 11022
EVENTS: list[dict[str, Any]] = []
DIAGNOSTICS_ENABLED = False


def record(path: str, payload: dict[str, Any], decision: str | None = None) -> None:
    client = payload.get("client_metadata") if isinstance(payload.get("client_metadata"), dict) else {}
    EVENTS.append(
        {
            "timestamp": datetime.now(timezone.utc).astimezone().isoformat(timespec="seconds"),
            "path": path,
            "session_id": payload.get("session_id"),
            "tool_name": payload.get("tool_name"),
            "decision": decision,
            "client": {
                "event_id": client.get("event_id"),
                "product": client.get("product"),
                "version": client.get("version"),
                "build_flavor": client.get("build_flavor"),
                "hook_action": client.get("hook_action"),
                "host": client.get("host"),
                "process_id": client.get("process_id"),
            },
        }
    )
    del EVENTS[:-100]


def page() -> bytes:
    return b"""<!doctype html><html><head><meta charset='utf-8'><title>ClaudeGuard Test Connector</title>
<style>body{font-family:Segoe UI,sans-serif;margin:2rem;background:#10151c;color:#e9eef5}pre{background:#18212c;padding:1rem;border-radius:8px}h1{color:#70d6a7}</style></head>
<body><h1>ClaudeGuard test connector :11022</h1><p>Test-only endpoint. Recent hook evidence:</p><pre id='events'>Waiting...</pre>
<script>async function refresh(){const r=await fetch('/events',{cache:'no-store'});document.querySelector('#events').textContent=JSON.stringify(await r.json(),null,2)}refresh();setInterval(refresh,750)</script></body></html>"""


class Handler(BaseHTTPRequestHandler):
    def log_message(self, _format: str, *_args: object) -> None:
        return

    def send_json(self, status: int, value: Any) -> None:
        body = json.dumps(value).encode("utf-8")
        self.send_response(status)
        self.send_header("Content-Type", "application/json")
        self.send_header("Cache-Control", "no-store")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def do_GET(self) -> None:
        path = urlparse(self.path).path
        if path == "/":
            if not DIAGNOSTICS_ENABLED:
                self.send_json(404, {"error": "local diagnostics disabled"})
                return
            body = page()
            self.send_response(200)
            self.send_header("Content-Type", "text/html; charset=utf-8")
            self.send_header("Content-Length", str(len(body)))
            self.end_headers()
            self.wfile.write(body)
        elif path == "/health":
            self.send_json(
                200,
                {
                    "ok": True,
                    "service": "claude-guard-test-connector",
                    "diagnostics_enabled": DIAGNOSTICS_ENABLED,
                },
            )
        elif path == "/events":
            if DIAGNOSTICS_ENABLED:
                self.send_json(200, EVENTS)
            else:
                self.send_json(404, {"error": "local diagnostics disabled"})
        else:
            self.send_json(404, {"error": "not found"})

    def do_POST(self) -> None:
        path = urlparse(self.path).path
        size = int(self.headers.get("Content-Length", "0"))
        try:
            payload = json.loads(self.rfile.read(size) or b"{}")
        except json.JSONDecodeError:
            self.send_json(400, {"error": "invalid JSON"})
            return

        if path == "/hook/pre-tool":
            command = str((payload.get("tool_input") or {}).get("command", ""))
            denied = "direct_db_client.py" in command or "fictitious" in command.lower()
            decision = "DENY" if denied else "ALLOW"
            record(path, payload, decision)
            self.send_json(
                200,
                {
                    "decision": decision,
                    "reason": "Test connector denied an unbrokered/fictitious access attempt."
                    if denied
                    else "Test connector allowed the action and registered its evidence.",
                },
            )
            return

        if path in {
            "/session/start",
            "/intent",
            "/hook/permission",
            "/hook/post-tool",
            "/session/end",
        }:
            record(path, payload)
            self.send_json(200, {"ok": True})
            return

        self.send_json(404, {"error": "not found"})


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="Test-only ClaudeGuard connector")
    parser.add_argument("--dashboard", action="store_true", help="Expose the lab diagnostics dashboard")
    arguments = parser.parse_args()
    DIAGNOSTICS_ENABLED = arguments.dashboard
    print(f"ClaudeGuard test connector listening on http://{HOST}:{PORT}", flush=True)
    if DIAGNOSTICS_ENABLED:
        print("LAB diagnostics dashboard: http://127.0.0.1:11022/", flush=True)
    else:
        print("Local diagnostics disabled (use --dashboard only when needed).", flush=True)
    ThreadingHTTPServer((HOST, PORT), Handler).serve_forever()
