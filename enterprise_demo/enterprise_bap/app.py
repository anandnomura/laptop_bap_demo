from __future__ import annotations

import argparse
import json
import secrets
import sys
import time
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from typing import Any
from urllib.parse import urlparse


DEMO_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(DEMO_ROOT))

from common.audit_store import AuditStore  # noqa: E402
from common.grants import sign_grant, verify_grant  # noqa: E402
from common.paths import PKI_ROOT, STATE_DB, ensure_runtime  # noqa: E402
from enterprise_bap.policy_engine import PolicyBundle, PolicyDecision  # noqa: E402


POLICY_PATH = Path(__file__).parent


class BAPApplication:
    def __init__(self, replica_id: str, store: AuditStore) -> None:
        self.replica_id = replica_id
        self.store = store
        self.policy = PolicyBundle(POLICY_PATH)

    def issue_grant(
        self,
        user: str,
        agent_run: str,
        action: str,
        resource: str,
        approved_by: str,
        policy: PolicyDecision,
    ) -> dict[str, Any]:
        now = int(time.time())
        grant_id = "gnt-" + secrets.token_hex(6)
        claims = {
            "iss": "enterprise-bap-demo",
            "aud": "enterprise-resource-gateway",
            "sub": user,
            "grant_id": grant_id,
            "agent_run": agent_run,
            "action": action,
            "resource": resource,
            "approved_by": approved_by,
            "policy_bundle_id": policy.bundle_id,
            "policy_rule_id": policy.rule_id,
            "policy_revision": policy.revision,
            "policy_bundle_sha256": policy.bundle_sha256,
            "iat": now,
            "exp": now + policy.grant_ttl_seconds,
            "jti": secrets.token_hex(12),
        }
        token = sign_grant(claims, PKI_ROOT / "bap-grant-signing.key.pem")
        with self.store.connect() as connection:
            connection.execute(
                "INSERT INTO grants(grant_id,token,agent_run,action,resource,expires_at,approved_by,policy_rule_id,policy_revision,revoked) VALUES(?,?,?,?,?,?,?,?,?,0)",
                (grant_id, token, agent_run, action, resource, claims["exp"], approved_by, policy.rule_id, policy.revision),
            )
        self.store.emit(
            self.replica_id,
            "GRANT_ISSUED",
            f"Issued {policy.grant_ttl_seconds}-second grant {grant_id} under {policy.rule_id}",
            {key: value for key, value in claims.items() if key != "jti"},
            "success",
        )
        return {"grant_id": grant_id, "token": token, **claims}

    def authorize(self, payload: dict[str, Any], mtls_subject: str) -> tuple[int, dict[str, Any]]:
        required = ("user", "device", "agent", "agent_run", "task", "action", "resource")
        missing = [key for key in required if not payload.get(key)]
        if missing:
            return 400, {"decision": "DENY", "reason": f"Missing authorization fields: {', '.join(missing)}"}

        action = str(payload["action"])
        resource = str(payload["resource"])
        user = str(payload["user"])
        agent_run = str(payload["agent_run"])
        evidence = {
            "replica": self.replica_id,
            "mtls_client": mtls_subject,
            "user": user,
            "device": payload["device"],
            "agent": payload["agent"],
            "agent_run": agent_run,
            "action": action,
            "resource": resource,
            "task": str(payload["task"])[:300],
        }
        self.store.emit(self.replica_id, "AUTHORIZATION_REQUEST", f"Evaluating {action} on {resource}", evidence)

        try:
            policy = self.policy.evaluate(payload)
        except (OSError, ValueError, json.JSONDecodeError) as error:
            self.store.emit(self.replica_id, "POLICY_BUNDLE_ERROR", "Policy bundle failed validation; denied request", {**evidence, "error": str(error)}, "error")
            return 200, {"decision": "DENY", "reason": "Enterprise policy is unavailable or invalid; failed closed"}

        policy_evidence = {
            **evidence,
            "policy_bundle_id": policy.bundle_id,
            "policy_revision": policy.revision,
            "policy_rule_id": policy.rule_id,
            "policy_bundle_sha256": policy.bundle_sha256,
        }
        self.store.emit(
            self.replica_id,
            "POLICY_MATCHED",
            f"{policy.rule_id} returned {policy.effect}",
            policy_evidence,
            "error" if policy.effect == "DENY" else "warning" if policy.effect == "REQUIRE_APPROVAL" else "success",
        )

        decision_metadata = {
            "policy": {
                "bundle_id": policy.bundle_id,
                "revision": policy.revision,
                "rule_id": policy.rule_id,
                "bundle_sha256": policy.bundle_sha256,
            }
        }
        if policy.effect == "ALLOW":
            grant = self.issue_grant(user, agent_run, action, resource, approved_by="policy", policy=policy)
            return 200, {
                "decision": "ALLOW",
                "reason": policy.reason,
                "replica": self.replica_id,
                "grant": grant,
                **decision_metadata,
            }

        if policy.effect == "REQUIRE_APPROVAL":
            request_id = "apr-" + secrets.token_hex(6)
            with self.store.connect() as connection:
                connection.execute(
                    "INSERT INTO approvals(request_id,user_id,agent_run,action,resource,policy_rule_id,policy_revision,grant_ttl_seconds,request_json,status) VALUES(?,?,?,?,?,?,?,?,?,'PENDING')",
                    (request_id, user, agent_run, action, resource, policy.rule_id, policy.revision, policy.grant_ttl_seconds, json.dumps(payload)),
                )
            self.store.emit(
                self.replica_id,
                "APPROVAL_REQUIRED",
                f"Created approval request {request_id} for {action}",
                {**policy_evidence, "approval_request_id": request_id},
                "warning",
            )
            return 200, {
                "decision": "REQUIRE_APPROVAL",
                "reason": policy.reason,
                "replica": self.replica_id,
                "approval_request_id": request_id,
                **decision_metadata,
            }

        self.store.emit(
            self.replica_id,
            "POLICY_DENY",
            f"Denied {action} on {resource}",
            policy_evidence,
            "error",
        )
        return 200, {
            "decision": "DENY",
            "reason": policy.reason,
            "replica": self.replica_id,
            **decision_metadata,
        }

    def approve(self, payload: dict[str, Any]) -> tuple[int, dict[str, Any]]:
        request_id = str(payload.get("request_id", ""))
        approver = str(payload.get("approver", ""))
        with self.store.connect() as connection:
            row = connection.execute(
                "SELECT * FROM approvals WHERE request_id=?", (request_id,)
            ).fetchone()
            if not row or row["status"] != "PENDING":
                return 404, {"ok": False, "reason": "Approval request is missing or no longer pending"}
            connection.execute("UPDATE approvals SET status='APPROVED' WHERE request_id=?", (request_id,))
        original_request = json.loads(row["request_json"])
        policy = self.policy.evaluate(original_request, human_approved=True)
        if policy.effect != "ALLOW":
            self.store.emit(
                self.replica_id,
                "APPROVAL_POLICY_REJECTED",
                f"Approval {request_id} did not satisfy current Cedar policy",
                {"request_id": request_id, "policy_rule_id": policy.rule_id},
                "error",
            )
            return 403, {"ok": False, "reason": "Current Cedar policy does not permit the approved action"}
        grant = self.issue_grant(
            row["user_id"], row["agent_run"], row["action"], row["resource"], approved_by=approver, policy=policy
        )
        self.store.emit(
            self.replica_id,
            "HUMAN_APPROVED",
            f"{approver} approved {request_id}",
            {"request_id": request_id, "grant_id": grant["grant_id"]},
            "success",
        )
        return 200, {"ok": True, "grant": grant}

    def validate(self, payload: dict[str, Any]) -> tuple[int, dict[str, Any]]:
        token = str(payload.get("token", ""))
        valid, claims_or_reason = verify_grant(token, PKI_ROOT / "bap-grant-signing.public.pem")
        if not valid:
            return 403, {"valid": False, "reason": claims_or_reason}
        claims = claims_or_reason
        assert isinstance(claims, dict)
        with self.store.connect() as connection:
            row = connection.execute(
                "SELECT revoked FROM grants WHERE grant_id=?", (claims.get("grant_id"),)
            ).fetchone()
        if not row or row["revoked"]:
            return 403, {"valid": False, "reason": "Grant is unknown or revoked"}
        for field in ("action", "resource", "agent_run"):
            if payload.get(field) != claims.get(field):
                return 403, {"valid": False, "reason": f"Grant {field} binding mismatch"}
        return 200, {"valid": True, "claims": claims}

    def revoke_session(self, payload: dict[str, Any]) -> tuple[int, dict[str, Any]]:
        agent_run = str(payload.get("agent_run", ""))
        with self.store.connect() as connection:
            count = connection.execute(
                "UPDATE grants SET revoked=1 WHERE agent_run=? AND revoked=0", (agent_run,)
            ).rowcount
        self.store.emit(
            self.replica_id,
            "SESSION_REVOKED",
            f"Revoked {count} grants for {agent_run}",
            {"agent_run": agent_run, "revoked_grants": count},
            "warning",
        )
        return 200, {"ok": True, "revoked_grants": count}

    def record_audit(self, payload: dict[str, Any], mtls_subject: str) -> tuple[int, dict[str, Any]]:
        details = payload.get("details") if isinstance(payload.get("details"), dict) else {}
        details = {**details, "mtls_client": mtls_subject, "replica": self.replica_id}
        self.store.emit(
            str(payload.get("source", "LAPTOP CONNECTOR"))[:80],
            str(payload.get("kind", "CLIENT_EVENT"))[:80],
            str(payload.get("message", "Connector event"))[:500],
            details,
            str(payload.get("level", "info")) if payload.get("level") in {"info", "success", "warning", "error"} else "info",
        )
        return 200, {"ok": True, "replica": self.replica_id}


def build_server(port: int, app: BAPApplication) -> ThreadingHTTPServer:
    class Handler(BaseHTTPRequestHandler):
        def log_message(self, _format: str, *_args: object) -> None:
            return

        def send_json(self, status: int, value: dict[str, Any]) -> None:
            body = json.dumps(value).encode()
            self.send_response(status)
            self.send_header("Content-Type", "application/json")
            self.send_header("Content-Length", str(len(body)))
            self.end_headers()
            self.wfile.write(body)

        def read_json(self) -> dict[str, Any]:
            length = int(self.headers.get("Content-Length", "0"))
            return json.loads(self.rfile.read(length) or b"{}")

        def do_GET(self) -> None:
            if urlparse(self.path).path == "/health":
                self.send_json(200, {"ok": True, "service": "enterprise-bap", "replica": app.replica_id})
            else:
                self.send_json(404, {"error": "not found"})

        def do_POST(self) -> None:
            path = urlparse(self.path).path
            payload = self.read_json()
            subject = self.headers.get("X-Demo-mTLS-Client", "missing")
            if path == "/authorize":
                status, result = app.authorize(payload, subject)
            elif path == "/approve":
                status, result = app.approve(payload)
            elif path == "/validate":
                status, result = app.validate(payload)
            elif path == "/revoke-session":
                status, result = app.revoke_session(payload)
            elif path == "/audit":
                status, result = app.record_audit(payload, subject)
            else:
                status, result = 404, {"error": "not found"}
            self.send_json(status, result)

    return ThreadingHTTPServer(("127.0.0.1", port), Handler)


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--port", type=int, required=True)
    parser.add_argument("--replica-id", required=True)
    arguments = parser.parse_args()
    ensure_runtime()
    store = AuditStore(STATE_DB)
    app = BAPApplication(arguments.replica_id, store)
    store.emit(arguments.replica_id, "REPLICA_READY", f"BAP replica listening on 127.0.0.1:{arguments.port}")
    build_server(arguments.port, app).serve_forever()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
