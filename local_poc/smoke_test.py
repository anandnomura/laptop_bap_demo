from __future__ import annotations

import json
import os
import socket
import subprocess
import sys
import threading
from pathlib import Path
from typing import Any

from demo_common import EventBus, json_request
from laptop_connector import LaptopConnectorState, build_connector_server
from mock_bap_server import MockBAPState, build_bap_server
from mock_db_server import MockDatabaseState, build_db_server


ROOT = Path(__file__).resolve().parent
HOOK = ROOT / "hooks" / "bap_hook.py"
TEST_ENV = os.environ.copy()


def run_hook(name: str, payload: dict[str, Any]) -> dict[str, Any]:
    result = subprocess.run(
        [sys.executable, str(HOOK), name],
        input=json.dumps(payload),
        text=True,
        capture_output=True,
        cwd=ROOT,
        env=TEST_ENV,
        check=False,
    )
    if result.returncode != 0:
        raise AssertionError(f"Hook {name} failed: {result.stderr}")
    return json.loads(result.stdout) if result.stdout.strip() else {}


def pre_tool(session_id: str, command: str, tool_id: str) -> dict[str, Any]:
    return run_hook(
        "authorize",
        {
            "session_id": session_id,
            "hook_event_name": "PreToolUse",
            "tool_name": "Bash",
            "tool_use_id": tool_id,
            "cwd": str(ROOT),
            "tool_input": {"command": command, "description": command},
        },
    )


def decision(result: dict[str, Any]) -> str:
    return str(result["hookSpecificOutput"]["permissionDecision"])


def free_port() -> int:
    with socket.socket() as sock:
        sock.bind(("127.0.0.1", 0))
        return int(sock.getsockname()[1])


def main() -> int:
    bap_port, connector_port, db_port = (free_port() for _ in range(3))
    bap_url = f"http://127.0.0.1:{bap_port}"
    connector_url = f"http://127.0.0.1:{connector_port}"
    db_url = f"http://127.0.0.1:{db_port}"
    TEST_ENV["BAP_CONNECTOR_URL"] = connector_url
    events = EventBus()
    db_state = MockDatabaseState(events)
    bap_state = MockBAPState(events)
    connector_state = LaptopConnectorState(events, db_state, bap_url=bap_url, db_url=db_url)
    servers = [
        build_bap_server("127.0.0.1", bap_port, bap_state),
        build_db_server("127.0.0.1", db_port, db_state),
        build_connector_server("127.0.0.1", connector_port, connector_state),
    ]
    threads = [threading.Thread(target=server.serve_forever, daemon=True) for server in servers]
    for thread in threads:
        thread.start()

    try:
        no_grant_status, no_grant = json_request(
            f"{connector_url}/db/execute",
            {"session_id": "not-registered", "operation": "read", "key": "customer-123"},
        )
        assert no_grant_status == 403 and not no_grant.get("ok"), no_grant
        fake_status, fake_result = json_request(
            f"{connector_url}/demo/external-grant-attempt",
            {
                "token": "eyJhbGciOiJIUzI1NiJ9.eyJncmFudF9pZCI6ImZha2UifQ.ZmljdGl0aW91cw",
                "action": "database.read",
                "resource": "dev-customer-db",
                "agent_run": "fictitious-run",
            },
        )
        assert fake_status == 403 and fake_result.get("forwarded_to_database") is False, fake_result
        negative_kinds = [event["kind"] for event in events.snapshot()]
        assert "NO_GRANT_DENIED" in negative_kinds
        assert "FICTITIOUS_GRANT_DENIED" in negative_kinds
        assert "QUERY_EXECUTED" not in negative_kinds

        session_id = "smoke-session"
        run_hook("session-start", {"session_id": session_id, "cwd": str(ROOT)})
        run_hook("capture-intent", {"session_id": session_id, "prompt": "Investigate customer-123"})

        read = pre_tool(session_id, "python tools/db_client.py read customer-123", "tool-read")
        assert decision(read) == "allow", read
        read_command = read["hookSpecificOutput"]["updatedInput"]["command"]
        read_result = subprocess.run(
            read_command, shell=True, cwd=ROOT, env=TEST_ENV, text=True, capture_output=True, check=False
        )
        assert read_result.returncode == 0, read_result.stdout + read_result.stderr
        assert '"name": "Ada"' in read_result.stdout, read_result.stdout

        write = pre_tool(
            session_id,
            "python tools/db_client.py write customer-123 status=reviewed",
            "tool-write",
        )
        assert decision(write) == "ask", write
        write_command = write["hookSpecificOutput"]["updatedInput"]["command"]
        write_result = subprocess.run(
            write_command, shell=True, cwd=ROOT, env=TEST_ENV, text=True, capture_output=True, check=False
        )
        assert write_result.returncode == 0, write_result.stdout + write_result.stderr
        assert '"status": "reviewed"' in write_result.stdout, write_result.stdout

        denied = pre_tool(session_id, "python tools/db_client.py delete customer-123", "tool-delete")
        assert decision(denied) == "deny", denied

        bypass = pre_tool(session_id, "python tools/direct_db_client.py", "tool-bypass")
        assert decision(bypass) == "deny", bypass

        direct_status, _ = json_request(
            f"{db_url}/query",
            {"operation": "read", "key": "customer-123"},
        )
        assert direct_status == 403, direct_status

        run_hook("session-end", {"session_id": session_id})
        assert len(events.snapshot()) >= 15
        print("\nSMOKE TEST PASSED")
        print("  [PASS] SessionStart registered a Claude agent run")
        print("  [PASS] Unregistered execution without a grant was denied")
        print("  [PASS] Fictitious caller-supplied grant was rejected and not forwarded")
        print("  [PASS] Development read received and validated a short-lived grant")
        print("  [PASS] Development write required approval and then executed")
        print("  [PASS] Destructive database operation was denied")
        print("  [PASS] Direct database path was rejected")
        print("  [PASS] SessionEnd revoked the run's grants")
        return 0
    finally:
        for server in servers:
            server.shutdown()
            server.server_close()
        for thread in threads:
            thread.join(timeout=2)


if __name__ == "__main__":
    raise SystemExit(main())
