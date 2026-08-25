from __future__ import annotations

import argparse
import json
import secrets
import ssl
import sys
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from urllib.parse import urlparse


DEMO_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(DEMO_ROOT))

from common.audit_store import AuditStore  # noqa: E402
from common.grants import verify_grant  # noqa: E402
from common.http_json import request_json  # noqa: E402
from common.paths import (  # noqa: E402
    PKI_ROOT,
    PROTECTED_RESOURCE_PORT,
    RESOURCE_GATEWAY_PORT,
    STATE_DB,
    ensure_runtime,
)
from common.tls import mtls_server_context  # noqa: E402
from protected_resource.app import GATEWAY_SECRET  # noqa: E402


def peer_subject(connection: ssl.SSLSocket) -> str:
    certificate = connection.getpeercert()
    return ",".join(
        f"{key}={value}" for group in certificate.get("subject", []) for key, value in group
    ) or "unknown-client"


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
                self.send_json(200, {"ok": True, "service": "resource-gateway"})
            else:
                self.send_json(404, {"error": "not found"})

        def do_POST(self) -> None:
            if urlparse(self.path).path != "/execute":
                store.emit("RESOURCE GATEWAY", "UNKNOWN_ROUTE_DENIED", "Rejected unknown resource-gateway route", {"request_path": urlparse(self.path).path, "decision": "DENY", "decision_reason": "Unknown route", "outcome": "DENIED"}, "error")
                self.send_json(404, {"error": "not found"})
                return
            length = int(self.headers.get("Content-Length", "0"))
            try:
                payload = json.loads(self.rfile.read(length) or b"{}")
                if not isinstance(payload, dict):
                    raise ValueError("JSON body must be an object")
            except (json.JSONDecodeError, ValueError) as error:
                request_id = "req-" + secrets.token_hex(12)
                store.emit("RESOURCE GATEWAY", "MALFORMED_REQUEST_DENIED", "Rejected malformed gateway request", {"request_id": request_id, "decision": "DENY", "decision_reason": "Malformed JSON", "outcome": "DENIED", "error": str(error)}, "error")
                self.send_json(400, {"ok": False, "error": "malformed JSON", "request_id": request_id})
                return
            subject = peer_subject(self.connection)
            trace_id = str(payload.get("trace_id") or "trc-" + secrets.token_hex(12))
            request_id = str(payload.get("request_id") or "req-" + secrets.token_hex(12))
            decision_id = str(payload.get("decision_id") or "dec-unknown")
            execution_id = "exe-" + secrets.token_hex(12)
            base = {
                "trace_id": trace_id,
                "request_id": request_id,
                "decision_id": decision_id,
                "execution_id": execution_id,
                "agent_run": payload.get("agent_run"),
                "action": payload.get("action"),
                "resource": payload.get("resource"),
                "resource_key": payload.get("key"),
                "mtls_subject": subject,
                "request_payload_hash": store.payload_hash({**payload, "token": "[REDACTED]"}),
            }
            valid, claims_or_reason = verify_grant(
                str(payload.get("token", "")), PKI_ROOT / "bap-grant-signing.public.pem"
            )
            if not valid:
                store.emit(
                    "RESOURCE GATEWAY",
                    "GRANT_REJECTED",
                    str(claims_or_reason),
                    {**base, "decision": "DENY", "decision_reason": str(claims_or_reason), "outcome": "DENIED", "http_status": 403},
                    "error",
                )
                self.send_json(403, {"ok": False, "error": claims_or_reason, "request_id": request_id, "execution_id": execution_id})
                return
            claims = claims_or_reason
            assert isinstance(claims, dict)
            bindings = {
                "action": payload.get("action"),
                "resource": payload.get("resource"),
                "agent_run": payload.get("agent_run"),
            }
            mismatch = next((key for key, value in bindings.items() if claims.get(key) != value), None)
            if mismatch:
                reason = f"Grant {mismatch} binding mismatch"
                store.emit("RESOURCE GATEWAY", "EXECUTION_DENIED", reason, {**base, "claims": claims, "decision": "DENY", "decision_reason": reason, "outcome": "DENIED", "http_status": 403}, "error")
                self.send_json(403, {"ok": False, "error": f"Grant {mismatch} binding mismatch", "request_id": request_id, "execution_id": execution_id})
                return
            with store.connect() as connection:
                row = connection.execute(
                    "SELECT revoked FROM grants WHERE grant_id=?", (claims.get("grant_id"),)
                ).fetchone()
            if not row or row["revoked"]:
                store.emit("RESOURCE GATEWAY", "EXECUTION_DENIED", "Grant is unknown or revoked", {**base, "claims": claims, "decision": "DENY", "decision_reason": "Grant is unknown or revoked", "outcome": "DENIED", "http_status": 403}, "error")
                self.send_json(403, {"ok": False, "error": "Grant is unknown or revoked", "request_id": request_id, "execution_id": execution_id})
                return
            store.emit(
                "RESOURCE GATEWAY",
                "GRANT_VALID",
                f"Validated {claims['grant_id']} independently before resource access",
                {**base, "claims": {key: value for key, value in claims.items() if key != "jti"}, "decision": "ALLOW", "decision_reason": "Grant signature, state, expiry and bindings are valid", "outcome": "AUTHORIZED"},
                "success",
            )
            operation = str(payload.get("operation", "read"))
            expected_action = {"read": "database.read", "write": "database.write"}.get(operation)
            if expected_action != claims.get("action"):
                reason = "Runtime operation differs from granted action"
                store.emit("RESOURCE GATEWAY", "EXECUTION_DENIED", reason, {**base, "claims": claims, "operation": operation, "decision": "DENY", "decision_reason": reason, "outcome": "DENIED", "http_status": 403}, "error")
                self.send_json(403, {"ok": False, "error": "Runtime operation differs from granted action", "request_id": request_id, "execution_id": execution_id})
                return
            status, result = request_json(
                f"http://127.0.0.1:{PROTECTED_RESOURCE_PORT}/query",
                {
                    "operation": operation,
                    "key": payload.get("key", "customer-123"),
                    "value": payload.get("value"),
                    "grant_id": claims["grant_id"],
                    "trace_id": trace_id,
                    "request_id": request_id,
                    "decision_id": decision_id,
                    "execution_id": execution_id,
                    "user_id": claims.get("sub"),
                    "agent_run": claims.get("agent_run"),
                    "action": claims.get("action"),
                    "resource": claims.get("resource"),
                },
                headers={"X-Resource-Gateway-Secret": GATEWAY_SECRET},
            )
            outcome = "SUCCEEDED" if status == 200 and result.get("ok") else "FAILED"
            store.emit(
                "RESOURCE GATEWAY",
                "EXECUTION_RESULT",
                f"Protected resource returned HTTP {status}",
                {**base, "claims": {key: value for key, value in claims.items() if key != "jti"}, "http_status": status, "outcome": outcome, "result_payload_hash": store.payload_hash(result)},
                "success" if outcome == "SUCCEEDED" else "error",
            )
            self.send_json(status, {**result, "execution_id": execution_id, "bap_evidence": {key: value for key, value in claims.items() if key != "jti"}})

    server = ThreadingHTTPServer(("127.0.0.1", port), Handler)
    context = mtls_server_context(
        PKI_ROOT / "resource-gateway.cert.pem",
        PKI_ROOT / "resource-gateway.key.pem",
        PKI_ROOT / "demo-ca.cert.pem",
    )
    server.socket = context.wrap_socket(server.socket, server_side=True)
    return server


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--port", type=int, default=RESOURCE_GATEWAY_PORT)
    arguments = parser.parse_args()
    ensure_runtime()
    store = AuditStore(STATE_DB)
    store.emit("RESOURCE GATEWAY", "SERVICE_READY", f"mTLS resource gateway listening on 127.0.0.1:{arguments.port}")
    build_server(arguments.port, store).serve_forever()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
