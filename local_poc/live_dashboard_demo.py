from __future__ import annotations

import json
import subprocess
import sys
import uuid
from pathlib import Path
from typing import Any

from demo_common import json_request


ROOT = Path(__file__).resolve().parent
HOOK = ROOT / "hooks" / "bap_hook.py"
CONNECTOR_URL = "http://127.0.0.1:8765"


def run_hook(action: str, payload: dict[str, Any]) -> dict[str, Any]:
    result = subprocess.run(
        [sys.executable, HOOK, action],
        input=json.dumps(payload),
        text=True,
        capture_output=True,
        cwd=ROOT,
        check=False,
    )
    if result.returncode != 0:
        raise RuntimeError(f"Hook {action} failed: {result.stderr.strip()}")
    return json.loads(result.stdout) if result.stdout.strip() else {}


def authorize(session_id: str, command: str, tool_id: str) -> dict[str, Any]:
    result = run_hook(
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
    return result["hookSpecificOutput"]


def execute_authorized(decision: dict[str, Any]) -> dict[str, Any]:
    command = decision["updatedInput"]["command"]
    result = subprocess.run(command, shell=True, cwd=ROOT, text=True, capture_output=True, check=False)
    if result.returncode != 0:
        raise RuntimeError(result.stdout + result.stderr)
    return json.loads(result.stdout)


def main() -> int:
    status, health = json_request(f"{CONNECTOR_URL}/health", method="GET", timeout=2)
    if status != 200 or not health.get("ok"):
        print("The live POC is not running. Start `py -3 run_demo.py` first.", file=sys.stderr)
        return 2

    session_id = "live-dashboard-" + uuid.uuid4().hex[:8]
    started = False
    try:
        run_hook("session-start", {"session_id": session_id, "cwd": str(ROOT)})
        started = True
        run_hook(
            "capture-intent",
            {"session_id": session_id, "prompt": "Demonstrate BAP read, approval, and deny decisions"},
        )

        read = authorize(session_id, "py -3 tools/db_client.py read customer-123", "live-read")
        assert read["permissionDecision"] == "allow", read
        read_result = execute_authorized(read)

        write = authorize(
            session_id,
            "py -3 tools/db_client.py write customer-123 status=leadership-demo",
            "live-write",
        )
        assert write["permissionDecision"] == "ask", write
        write_result = execute_authorized(write)

        delete = authorize(session_id, "py -3 tools/db_client.py delete customer-123", "live-delete")
        assert delete["permissionDecision"] == "deny", delete

        production = authorize(session_id, "py -3 tools/db_client.py prod-read customer-123", "live-prod")
        assert production["permissionDecision"] == "deny", production

        print("LIVE DASHBOARD DEMO PASSED")
        print(f"  [ALLOW] read returned {read_result['record']['name']}")
        print(f"  [ASK/ALLOW] approved write set status={write_result['record']['status']}")
        print("  [DENY] destructive delete was not executed")
        print("  [DENY] production read was not executed")
        print("  Watch http://127.0.0.1:8765 for the complete event sequence.")
        return 0
    finally:
        if started:
            run_hook("session-end", {"session_id": session_id})


if __name__ == "__main__":
    raise SystemExit(main())
