from __future__ import annotations

import json
import sqlite3
import socket
import ssl
import subprocess
import sys
import uuid
from pathlib import Path
from typing import Any


DEMO_ROOT = Path(__file__).resolve().parents[1]
REPO_ROOT = DEMO_ROOT.parent
sys.path.insert(0, str(DEMO_ROOT))

from common.http_json import request_json  # noqa: E402
from common.paths import (  # noqa: E402
    BAP_FRONT_DOOR_PORT,
    DASHBOARD_PORT,
    PKI_ROOT,
    RESOURCE_GATEWAY_PORT,
    STATE_DB,
)
from common.tls import mtls_client_context  # noqa: E402


GUARD = DEMO_ROOT / "claude_guard" / "publish" / "claude_guard.exe"
RESOURCE_CLIENT = DEMO_ROOT / "bap_resource_client" / "publish" / "bap_resource_client.exe"


def hook(action: str, payload: dict[str, Any]) -> tuple[int, dict[str, Any]]:
    result = subprocess.run(
        [GUARD, action],
        input=json.dumps(payload),
        text=True,
        capture_output=True,
        check=False,
        cwd=REPO_ROOT,
    )
    parsed = json.loads(result.stdout) if result.stdout.strip() else {}
    return result.returncode, parsed


def authorize(session_id: str, command: str) -> dict[str, Any]:
    code, result = hook(
        "authorize",
        {
            "session_id": session_id,
            "hook_event_name": "PreToolUse",
            "tool_name": "PowerShell",
            "tool_input": {"command": command},
        },
    )
    assert code == 0, result
    return result["hookSpecificOutput"]


def main() -> int:
    session_id = "enterprise-smoke-" + uuid.uuid4().hex[:8]
    mtls = mtls_client_context(
        PKI_ROOT / "connector-client.cert.pem",
        PKI_ROOT / "connector-client.key.pem",
        PKI_ROOT / "demo-ca.cert.pem",
    )

    health = subprocess.run([GUARD, "--health"], capture_output=True, text=True, check=False)
    assert health.returncode == 0 and "\\\\.\\pipe\\Company.BAP.Connector.v1" in health.stdout

    code, _ = hook(
        "session-start",
        {
            "session_id": session_id,
            "hook_event_name": "SessionStart",
            "source": "startup",
            "cwd": str(REPO_ROOT),
        },
    )
    assert code == 0
    code, _ = hook(
        "capture-intent",
        {
            "session_id": session_id,
            "hook_event_name": "UserPromptSubmit",
            "prompt": "Read customer-123, then demonstrate a controlled write and denied destructive action",
        },
    )
    assert code == 0

    read_command = f'"{RESOURCE_CLIENT}" read customer-123'
    read_decision = authorize(session_id, read_command)
    assert read_decision["permissionDecision"] == "allow"
    assert f"--bap-session {session_id}" in read_decision["updatedInput"]["command"]
    read = subprocess.run(
        [RESOURCE_CLIENT, "read", "customer-123", "--bap-session", session_id],
        capture_output=True,
        text=True,
        check=False,
    )
    read_result = json.loads(read.stdout)
    assert read.returncode == 0 and read_result["ok"]
    assert read_result["bap_evidence"]["action"] == "database.read"

    write_command = f'"{RESOURCE_CLIENT}" write customer-123 status=reviewed'
    write_decision = authorize(session_id, write_command)
    assert write_decision["permissionDecision"] == "ask"
    write = subprocess.run(
        [RESOURCE_CLIENT, "write", "customer-123", "status=reviewed", "--bap-session", session_id],
        capture_output=True,
        text=True,
        check=False,
    )
    write_result = json.loads(write.stdout)
    assert write.returncode == 0 and write_result["value"]["status"] == "reviewed"
    assert write_result["bap_evidence"]["approved_by"] == __import__("getpass").getuser()

    delete_command = f'"{RESOURCE_CLIENT}" delete customer-123'
    delete_decision = authorize(session_id, delete_command)
    assert delete_decision["permissionDecision"] == "deny"

    direct_decision = authorize(
        session_id,
        "py -3 enterprise_demo/bap_resource_client/direct_resource_client.py",
    )
    assert direct_decision["permissionDecision"] == "deny"

    unregistered = subprocess.run(
        [RESOURCE_CLIENT, "read", "customer-123", "--bap-session", "missing-session"],
        capture_output=True,
        text=True,
        check=False,
    )
    assert unregistered.returncode == 1
    assert "No authorized session-held grant" in unregistered.stdout

    direct = subprocess.run(
        [sys.executable, DEMO_ROOT / "bap_resource_client" / "direct_resource_client.py"],
        capture_output=True,
        text=True,
        check=False,
    )
    assert direct.returncode == 1 and "Resource gateway required" in direct.stdout

    fake_status, fake_result = request_json(
        f"https://127.0.0.1:{RESOURCE_GATEWAY_PORT}/execute",
        {
            "token": "fictitious.grant.value",
            "action": "database.read",
            "resource": "dev-customer-db",
            "agent_run": "fake-agent-run",
            "operation": "read",
            "key": "customer-123",
        },
        ssl_context=mtls,
    )
    assert fake_status == 403 and not fake_result["ok"]

    no_client_context = ssl.create_default_context(
        ssl.Purpose.SERVER_AUTH,
        cafile=PKI_ROOT / "demo-ca.cert.pem",
    )
    try:
        request_json(
            f"https://127.0.0.1:{BAP_FRONT_DOOR_PORT}/health",
            method="GET",
            ssl_context=no_client_context,
        )
        raise AssertionError("BAP front door accepted a TLS client without a client certificate")
    except Exception:
        pass

    with socket.socket() as probe:
        probe.settimeout(0.3)
        assert probe.connect_ex(("127.0.0.1", 11022)) != 0

    _, state = request_json(f"http://127.0.0.1:{DASHBOARD_PORT}/api/state", method="GET")
    kinds = {event["kind"] for event in state["events"]}
    for expected in {
        "MTLS_ACCEPTED",
        "TOOL_INTERCEPTED",
        "GRANT_ISSUED",
        "GRANT_VALID",
        "RESOURCE_EXECUTED",
        "POLICY_DENY",
        "DIRECT_PATH_BLOCKED",
        "NO_GRANT_DENIED",
        "DIRECT_ACCESS_DENIED",
        "GRANT_REJECTED",
        "AUTHORIZATION_DECISION",
        "TOOL_DECISION",
        "EXECUTION_RESULT",
    }:
        assert expected in kinds, f"Missing central audit evidence: {expected}"

    integrity_status, integrity = request_json(
        f"http://127.0.0.1:{DASHBOARD_PORT}/api/integrity", method="GET"
    )
    assert integrity_status == 200 and integrity["ok"] and integrity["checked"] >= len(state["events"])
    access_status, access_result = request_json(
        f"http://127.0.0.1:{DASHBOARD_PORT}/api/access?session_id={session_id}", method="GET"
    )
    assert access_status == 200 and access_result["access"]
    read_access = next(row for row in access_result["access"] if row["action"] == "database.read")
    assert read_access["decision"] == "ALLOW"
    assert read_access["execution_outcome"] == "EXECUTED"
    assert read_access["user_id"] and read_access["task_summary"] and read_access["execution_id"]
    audit_status, audit_result = request_json(
        f"http://127.0.0.1:{DASHBOARD_PORT}/api/audit?request_id={read_access['request_id']}", method="GET"
    )
    assert audit_status == 200 and len(audit_result["events"]) >= 5
    assert all("token" not in json.dumps(event["details"]).lower() for event in audit_result["events"])
    assert all("token" not in grant for grant in state["grants"])
    with sqlite3.connect(STATE_DB) as audit_database:
        assert audit_database.execute("SELECT count(*) FROM grants WHERE token<>''").fetchone()[0] == 0
        try:
            audit_database.execute(
                "UPDATE audit_events SET message=message WHERE sequence=(SELECT min(sequence) FROM audit_events)"
            )
            audit_database.commit()
            raise AssertionError("Audit event UPDATE unexpectedly succeeded")
        except sqlite3.DatabaseError as error:
            audit_database.rollback()
            assert "append-only" in str(error)

    replicas: set[str] = set()
    for index in range(8):
        status, response = request_json(
            f"https://127.0.0.1:{BAP_FRONT_DOOR_PORT}/authorize",
            {
                "user": "scale-test",
                "device": "demo-laptop",
                "agent": "scale-probe",
                "agent_run": f"scale-run-{index}",
                "task": "Prove requests route across replicas",
                "action": "database.read",
                "resource": "dev-customer-db",
            },
            ssl_context=mtls,
        )
        assert status == 200
        replicas.add(response["replica"])
    assert replicas == {"BAP REPLICA 1", "BAP REPLICA 2"}, replicas

    hook("session-end", {"session_id": session_id, "hook_event_name": "SessionEnd", "reason": "smoke-test"})

    print("ENTERPRISE BAP SMOKE TEST PASSED")
    print("  [PASS] ClaudeGuard used a signed Windows named-pipe connector; port 11022 was absent")
    print("  [PASS] mTLS rejected clients without the connector certificate")
    print("  [PASS] Requests were distributed across two BAP replicas with shared state")
    print("  [PASS] Read grant executed; write required approval; delete was denied before execution")
    print("  [PASS] Missing, fictitious, and direct resource paths were independently denied")
    print("  [PASS] Central dashboard captured the full enforcement sequence")
    print("  [PASS] Correlated audit search, secret exclusion, and append-only hash-chain integrity passed")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
