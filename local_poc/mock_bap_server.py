from __future__ import annotations

import base64
import hashlib
import hmac
import json
import secrets
import threading
import time
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from typing import Any
from urllib.parse import urlparse

from demo_common import EventBus


class MockBAPState:
    def __init__(self, events: EventBus) -> None:
        self.events = events
        self.pending: dict[str, dict[str, Any]] = {}
        self.grants: dict[str, dict[str, Any]] = {}
        self.lock = threading.Lock()
        self.signing_key = b"demo-only-bap-signing-key"

    @staticmethod
    def classify_policy(action: str, resource: str) -> tuple[str, str]:
        if resource.startswith("prod-"):
            return "DENY", "Laptop agents cannot access production databases"
        if action in {"database.delete", "database.drop"}:
            return "DENY", "Destructive database operations are prohibited"
        if action == "database.write":
            return "REQUIRE_APPROVAL", "Development database writes require human approval"
        if action == "database.read" and resource.startswith("dev-"):
            return "ALLOW", "Development database reads are allowed for registered tasks"
        return "DENY", "No matching BAP policy permits this request"

    def authorize(self, request: dict[str, Any]) -> dict[str, Any]:
        decision, reason = self.classify_policy(
            str(request.get("action", "unknown")),
            str(request.get("resource", "unknown")),
        )
        common = {
            "decision": decision,
            "reason": reason,
            "agent_run": request.get("agent_run"),
            "user": request.get("user"),
            "action": request.get("action"),
            "resource": request.get("resource"),
        }

        if decision == "ALLOW":
            grant = self._mint_grant(request, approved_by="policy:dev-read-v1")
            common["grant"] = grant
            self.events.emit(
                "BAP SERVER",
                "GRANT_ISSUED",
                f"Issued 60-second grant {grant['grant_id']} for {request.get('action')}",
                grant,
                "success",
            )
        elif decision == "REQUIRE_APPROVAL":
            request_id = "apr-" + secrets.token_hex(4)
            with self.lock:
                self.pending[request_id] = {**request, "created_at": int(time.time())}
            common["approval_request_id"] = request_id
            self.events.emit(
                "BAP SERVER",
                "APPROVAL_NEEDED",
                f"Created approval request {request_id} for {request.get('action')}",
                common,
                "warning",
            )
        else:
            self.events.emit(
                "BAP SERVER",
                "POLICY_DENY",
                reason,
                common,
                "error",
            )
        return common

    def approve(self, request_id: str, approver: str) -> dict[str, Any]:
        with self.lock:
            request = self.pending.pop(request_id, None)
        if not request:
            return {"ok": False, "reason": "Approval request not found"}
        grant = self._mint_grant(request, approved_by=f"human:{approver}")
        self.events.emit(
            "BAP SERVER",
            "HUMAN_APPROVED",
            f"{approver} approved {request_id}; grant {grant['grant_id']} activated",
            grant,
            "success",
        )
        return {"ok": True, "grant": grant}

    def _mint_grant(self, request: dict[str, Any], approved_by: str) -> dict[str, Any]:
        now = int(time.time())
        grant_id = "gnt-" + secrets.token_hex(4)
        claims = {
            "grant_id": grant_id,
            "agent_run": request.get("agent_run"),
            "on_behalf_of": request.get("user"),
            "task": request.get("task"),
            "action": request.get("action"),
            "resource": request.get("resource"),
            "approved_by": approved_by,
            "iat": now,
            "exp": now + 60,
        }
        token = self._sign(claims)
        grant = {**claims, "token": token}
        with self.lock:
            self.grants[grant_id] = grant
        return grant

    def validate(self, token: str, action: str, resource: str, agent_run: str) -> dict[str, Any]:
        claims = self._verify(token)
        if not claims:
            return {"valid": False, "reason": "Invalid grant signature"}
        with self.lock:
            active_grant = self.grants.get(str(claims.get("grant_id", "")))
        if not active_grant:
            return {"valid": False, "reason": "Grant was revoked or is not active"}
        if int(claims.get("exp", 0)) < int(time.time()):
            return {"valid": False, "reason": "Grant expired"}
        if claims.get("action") != action:
            return {"valid": False, "reason": "Grant action mismatch"}
        if claims.get("resource") != resource:
            return {"valid": False, "reason": "Grant resource mismatch"}
        if claims.get("agent_run") != agent_run:
            return {"valid": False, "reason": "Grant agent-run mismatch"}
        return {"valid": True, "claims": claims}

    def revoke_session(self, agent_run: str) -> int:
        with self.lock:
            ids = [key for key, value in self.grants.items() if value.get("agent_run") == agent_run]
            for grant_id in ids:
                self.grants.pop(grant_id, None)
        return len(ids)

    def _sign(self, claims: dict[str, Any]) -> str:
        header = {"alg": "HS256", "typ": "BAP-DEMO"}

        def encode(value: dict[str, Any]) -> str:
            raw = json.dumps(value, separators=(",", ":"), sort_keys=True).encode("utf-8")
            return base64.urlsafe_b64encode(raw).rstrip(b"=").decode("ascii")

        unsigned = f"{encode(header)}.{encode(claims)}"
        signature = hmac.new(self.signing_key, unsigned.encode("ascii"), hashlib.sha256).digest()
        encoded_signature = base64.urlsafe_b64encode(signature).rstrip(b"=").decode("ascii")
        return f"{unsigned}.{encoded_signature}"

    def _verify(self, token: str) -> dict[str, Any] | None:
        try:
            header, payload, signature = token.split(".")
            unsigned = f"{header}.{payload}"
            expected = hmac.new(self.signing_key, unsigned.encode("ascii"), hashlib.sha256).digest()
            actual = base64.urlsafe_b64decode(signature + "=" * (-len(signature) % 4))
            if not hmac.compare_digest(expected, actual):
                return None
            decoded = base64.urlsafe_b64decode(payload + "=" * (-len(payload) % 4))
            return json.loads(decoded)
        except (ValueError, json.JSONDecodeError):
            return None


def build_bap_server(host: str, port: int, state: MockBAPState) -> ThreadingHTTPServer:
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
            if urlparse(self.path).path == "/health":
                self._send(200, {"ok": True, "service": "mock-bap"})
            else:
                self._send(404, {"error": "not found"})

        def do_POST(self) -> None:
            path = urlparse(self.path).path
            payload = self._read()
            if path == "/authorize":
                self._send(200, state.authorize(payload))
            elif path == "/approve":
                result = state.approve(str(payload.get("request_id")), str(payload.get("approver", "developer")))
                self._send(200 if result.get("ok") else 404, result)
            elif path == "/validate":
                result = state.validate(
                    str(payload.get("token", "")),
                    str(payload.get("action", "")),
                    str(payload.get("resource", "")),
                    str(payload.get("agent_run", "")),
                )
                self._send(200 if result.get("valid") else 403, result)
            elif path == "/revoke-session":
                count = state.revoke_session(str(payload.get("agent_run", "")))
                self._send(200, {"ok": True, "revoked": count})
            else:
                self._send(404, {"error": "not found"})

    return ThreadingHTTPServer((host, port), Handler)
