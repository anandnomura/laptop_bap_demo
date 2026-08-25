from __future__ import annotations

import argparse
import json
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
                self.send_json(404, {"error": "not found"})
                return
            length = int(self.headers.get("Content-Length", "0"))
            payload = json.loads(self.rfile.read(length) or b"{}")
            if self.headers.get("X-Resource-Gateway-Secret") != GATEWAY_SECRET:
                store.emit(
                    "PROTECTED RESOURCE",
                    "DIRECT_ACCESS_DENIED",
                    "Rejected a request that did not come through the resource gateway",
                    {"operation": payload.get("operation"), "key": payload.get("key")},
                    "error",
                )
                self.send_json(403, {"ok": False, "error": "Resource gateway required"})
                return
            operation = str(payload.get("operation", "read"))
            key = str(payload.get("key", "customer-123"))
            if operation == "read":
                result = DATA.get(key)
                if result is None:
                    self.send_json(404, {"ok": False, "error": "not found"})
                    return
                response = {"ok": True, "operation": operation, "key": key, "value": result}
            elif operation == "write":
                DATA.setdefault(key, {}).update(payload.get("value") or {})
                response = {"ok": True, "operation": operation, "key": key, "value": DATA[key]}
            else:
                self.send_json(403, {"ok": False, "error": "operation prohibited"})
                return
            store.emit(
                "PROTECTED RESOURCE",
                "RESOURCE_EXECUTED",
                f"Executed {operation.upper()} on {key} through the gateway",
                {"operation": operation, "key": key, "grant_id": payload.get("grant_id")},
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
