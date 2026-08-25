from __future__ import annotations

import argparse
import json
import secrets
import sys
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from urllib.parse import urlparse


DEMO_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(DEMO_ROOT))

from common.audit_store import AuditStore  # noqa: E402
from common.paths import PROTECTED_RESOURCE_PORT, STATE_DB, ensure_runtime  # noqa: E402


GATEWAY_SECRET = "demo-resource-gateway-only"
DATA = {"customer-123": {"name": "Alice Example", "status": "active", "tier": "gold"}}


def build_server(port: int, store: AuditStore) -> ThreadingHTTPServer:
    class Handler(BaseHTTPRequestHandler):
        def log_message(self, _format: str, *_args: object) -> None:
            return

        def send_json(self, status: int, value: dict) -> None:
            body = json.dumps(value).encode()
            self.send_response(status)
            self.send_header("Content-Type", "application/json")
            self.send_header("Content-Length", str(len(body)))
            self.end_headers()
            self.wfile.write(body)

        def do_GET(self) -> None:
            if urlparse(self.path).path == "/health":
                self.send_json(200, {"ok": True, "service": "protected-resource"})
            else:
                self.send_json(404, {"error": "not found"})

        def do_POST(self) -> None:
            if urlparse(self.path).path != "/query":
                store.emit("PROTECTED RESOURCE", "UNKNOWN_ROUTE_DENIED", "Rejected unknown protected-resource route", {"request_path": urlparse(self.path).path, "decision": "DENY", "decision_reason": "Unknown route", "outcome": "DENIED"}, "error")
                self.send_json(404, {"error": "not found"})
                return
            length = int(self.headers.get("Content-Length", "0"))
            try:
                payload = json.loads(self.rfile.read(length) or b"{}")
                if not isinstance(payload, dict):
                    raise ValueError("JSON body must be an object")
            except (json.JSONDecodeError, ValueError) as error:
                request_id = "req-" + secrets.token_hex(12)
                store.emit("PROTECTED RESOURCE", "MALFORMED_REQUEST_DENIED", "Rejected malformed protected-resource request", {"request_id": request_id, "decision": "DENY", "decision_reason": "Malformed JSON", "outcome": "DENIED", "error": str(error)}, "error")
                self.send_json(400, {"ok": False, "error": "malformed JSON", "request_id": request_id})
                return
            base = {
                "trace_id": payload.get("trace_id"),
                "request_id": payload.get("request_id"),
                "decision_id": payload.get("decision_id"),
                "execution_id": payload.get("execution_id"),
                "user_id": payload.get("user_id"),
                "agent_run": payload.get("agent_run"),
                "action": payload.get("action"),
                "resource": payload.get("resource"),
                "resource_key": payload.get("key"),
                "grant_id": payload.get("grant_id"),
                "request_payload_hash": store.payload_hash(payload),
            }
            if self.headers.get("X-Resource-Gateway-Secret") != GATEWAY_SECRET:
                store.emit(
                    "PROTECTED RESOURCE",
                    "DIRECT_ACCESS_DENIED",
                    "Rejected a request that did not come through the resource gateway",
                    {**base, "operation": payload.get("operation"), "decision": "DENY", "decision_reason": "Resource gateway identity required", "outcome": "DENIED", "http_status": 403},
                    "error",
                )
                self.send_json(403, {"ok": False, "error": "Resource gateway required"})
                return
            operation = str(payload.get("operation", "read"))
            key = str(payload.get("key", "customer-123"))
            if operation == "read":
                result = DATA.get(key)
                if result is None:
                    store.emit("PROTECTED RESOURCE", "EXECUTION_RESULT", f"Resource key {key} was not found", {**base, "operation": operation, "http_status": 404, "outcome": "FAILED", "result_payload_hash": store.payload_hash({"error": "not found"})}, "warning")
                    self.send_json(404, {"ok": False, "error": "not found"})
                    return
                response = {"ok": True, "operation": operation, "key": key, "value": result}
            elif operation == "write":
                DATA.setdefault(key, {}).update(payload.get("value") or {})
                response = {"ok": True, "operation": operation, "key": key, "value": DATA[key]}
            else:
                store.emit("PROTECTED RESOURCE", "EXECUTION_DENIED", f"Operation {operation} is prohibited", {**base, "operation": operation, "decision": "DENY", "decision_reason": "Operation prohibited", "outcome": "DENIED", "http_status": 403}, "error")
                self.send_json(403, {"ok": False, "error": "operation prohibited"})
                return
            store.emit(
                "PROTECTED RESOURCE",
                "RESOURCE_EXECUTED",
                f"Executed {operation.upper()} on {key} through the gateway",
                {**base, "operation": operation, "http_status": 200, "outcome": "SUCCEEDED", "result_payload_hash": store.payload_hash(response)},
                "success",
            )
            self.send_json(200, response)

    return ThreadingHTTPServer(("127.0.0.1", port), Handler)


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--port", type=int, default=PROTECTED_RESOURCE_PORT)
    arguments = parser.parse_args()
    ensure_runtime()
    store = AuditStore(STATE_DB)
    store.emit("PROTECTED RESOURCE", "SERVICE_READY", f"Protected resource listening on 127.0.0.1:{arguments.port}")
    build_server(arguments.port, store).serve_forever()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
