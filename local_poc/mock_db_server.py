from __future__ import annotations

import json
import threading
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from typing import Any
from urllib.parse import urlparse

from demo_common import EventBus


GATEWAY_SECRET = "demo-gateway-to-database-secret"


class MockDatabaseState:
    def __init__(self, events: EventBus) -> None:
        self.events = events
        self.lock = threading.Lock()
        self.rows: dict[str, dict[str, Any]] = {
            "customer-123": {"name": "Ada", "status": "active", "risk": "low"},
            "customer-456": {"name": "Grace", "status": "review", "risk": "medium"},
        }

    def execute(self, payload: dict[str, Any]) -> tuple[int, dict[str, Any]]:
        operation = str(payload.get("operation", "read"))
        key = str(payload.get("key", "customer-123"))
        value = payload.get("value")
        with self.lock:
            if operation == "read":
                result = self.rows.get(key)
                if result is None:
                    return 404, {"ok": False, "error": "record not found"}
                response = {"ok": True, "operation": "read", "key": key, "record": result}
            elif operation == "write":
                record = self.rows.setdefault(key, {})
                if not isinstance(value, dict):
                    return 400, {"ok": False, "error": "write requires an object value"}
                record.update(value)
                response = {"ok": True, "operation": "write", "key": key, "record": record}
            elif operation == "delete":
                removed = self.rows.pop(key, None)
                response = {"ok": True, "operation": "delete", "key": key, "removed": removed}
            else:
                return 400, {"ok": False, "error": f"unsupported operation: {operation}"}

        self.events.emit(
            "MOCK DB",
            "QUERY_EXECUTED",
            f"Executed {operation.upper()} on {key}",
            {"operation": operation, "key": key, "agent_run": payload.get("agent_run")},
            "success",
        )
        return 200, response

    def snapshot(self) -> dict[str, dict[str, Any]]:
        with self.lock:
            return json.loads(json.dumps(self.rows))

    def reset(self) -> None:
        with self.lock:
            self.rows = {
                "customer-123": {"name": "Ada", "status": "active", "risk": "low"},
                "customer-456": {"name": "Grace", "status": "review", "risk": "medium"},
            }


def build_db_server(host: str, port: int, state: MockDatabaseState) -> ThreadingHTTPServer:
    class Handler(BaseHTTPRequestHandler):
        def log_message(self, _format: str, *_args: object) -> None:
            return

        def _read(self) -> dict[str, Any]:
            length = int(self.headers.get("Content-Length", "0"))
            return json.loads(self.rfile.read(length) or b"{}")

        def _send(self, status: int, value: dict[str, Any]) -> None:
            body = json.dumps(value).encode("utf-8")
            self.send_response(status)
            self.send_header("Content-Type", "application/json")
            self.send_header("Content-Length", str(len(body)))
            self.end_headers()
            self.wfile.write(body)

        def do_GET(self) -> None:
            path = urlparse(self.path).path
            if path == "/health":
                self._send(200, {"ok": True, "service": "mock-db"})
            elif path == "/data":
                self._send(200, {"ok": True, "rows": state.snapshot()})
            else:
                self._send(404, {"error": "not found"})

        def do_POST(self) -> None:
            path = urlparse(self.path).path
            if path != "/query":
                self._send(404, {"error": "not found"})
                return
            if self.headers.get("X-Demo-Gateway-Secret") != GATEWAY_SECRET:
                state.events.emit(
                    "MOCK DB",
                    "DIRECT_DENY",
                    "Rejected connection without the gateway credential",
                    {},
                    "error",
                )
                self._send(403, {"ok": False, "error": "gateway credential required"})
                return
            status, result = state.execute(self._read())
            self._send(status, result)

    return ThreadingHTTPServer((host, port), Handler)

