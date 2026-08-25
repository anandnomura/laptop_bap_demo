from __future__ import annotations

import json
import os
import sys
from pathlib import Path
from typing import Any


PROJECT_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(PROJECT_ROOT))

from demo_common import json_request  # noqa: E402


CONNECTOR_URL = os.environ.get("BAP_CONNECTOR_URL", "http://127.0.0.1:8765")


def read_event() -> dict[str, Any]:
    try:
        return json.load(sys.stdin)
    except json.JSONDecodeError:
        return {}


def emit_hook_decision(
    decision: str,
    reason: str,
    updated_input: dict[str, Any] | None = None,
) -> None:
    output: dict[str, Any] = {
        "hookSpecificOutput": {
            "hookEventName": "PreToolUse",
            "permissionDecision": decision,
            "permissionDecisionReason": reason,
        }
    }
    if updated_input is not None:
        output["hookSpecificOutput"]["updatedInput"] = updated_input
    print(json.dumps(output), flush=True)


def post(path: str, event: dict[str, Any]) -> tuple[int, dict[str, Any]]:
    return json_request(f"{CONNECTOR_URL}{path}", event, timeout=5)


def session_start(event: dict[str, Any]) -> int:
    event["user"] = os.environ.get("USERNAME") or os.environ.get("USER") or "developer"
    status, _ = post("/session/start", event)
    return 0 if status == 200 else 2


def capture_intent(event: dict[str, Any]) -> int:
    status, _ = post("/intent", event)
    return 0 if status == 200 else 2


def pre_tool(event: dict[str, Any]) -> int:
    try:
        status, result = post("/hook/pre-tool", event)
    except Exception as exc:
        emit_hook_decision("deny", f"Laptop BAP connector unavailable; fail closed: {exc}")
        return 0
    if status != 200:
        emit_hook_decision("deny", "Laptop BAP connector rejected the authorization request")
        return 0

    decision = str(result.get("decision", "DENY"))
    reason = str(result.get("reason", "No BAP decision reason supplied"))
    updated_input = dict(event.get("tool_input") or {})

    # For the protected demo client, bind the command to this exact Claude session.
    # The connector keeps the signed grant; the grant is never exposed in the shell.
    if (
        event.get("tool_name") == "Bash"
        and "db_client.py" in str(updated_input.get("command", ""))
        and "direct_db_client.py" not in str(updated_input.get("command", ""))
        and "--bap-session" not in str(updated_input.get("command", ""))
    ):
        updated_input["command"] = (
            str(updated_input.get("command", ""))
            + " --bap-session "
            + str(event.get("session_id", ""))
        )

    if decision == "ALLOW":
        emit_hook_decision("allow", reason, updated_input)
    elif decision == "REQUIRE_APPROVAL":
        emit_hook_decision("ask", reason, updated_input)
    else:
        emit_hook_decision("deny", reason)
    return 0


def permission_request(event: dict[str, Any]) -> int:
    # This hook records that Claude displayed its approval UI. It deliberately
    # returns no allow/deny decision, leaving the choice to the developer.
    status, _ = post("/hook/permission", event)
    return 0 if status == 200 else 2


def post_tool(event: dict[str, Any]) -> int:
    status, _ = post("/hook/post-tool", event)
    return 0 if status == 200 else 2


def session_end(event: dict[str, Any]) -> int:
    status, _ = post("/session/end", event)
    return 0 if status == 200 else 2


HANDLERS = {
    "session-start": session_start,
    "capture-intent": capture_intent,
    "authorize": pre_tool,
    "permission-request": permission_request,
    "post-tool": post_tool,
    "session-end": session_end,
}


def main() -> int:
    if len(sys.argv) != 2 or sys.argv[1] not in HANDLERS:
        print("Usage: bap_hook.py <session-start|capture-intent|authorize|permission-request|post-tool|session-end>", file=sys.stderr)
        return 2
    event = read_event()
    try:
        return HANDLERS[sys.argv[1]](event)
    except Exception as exc:
        if sys.argv[1] == "authorize":
            emit_hook_decision("deny", f"BAP hook failed closed: {exc}")
            return 0
        print(f"BAP hook error: {exc}", file=sys.stderr)
        return 2


if __name__ == "__main__":
    raise SystemExit(main())

