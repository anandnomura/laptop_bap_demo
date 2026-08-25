from __future__ import annotations

import argparse
import json
import os
import sys
from pathlib import Path
from typing import Any


PROJECT_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(PROJECT_ROOT))

from demo_common import json_request  # noqa: E402


def parse_assignments(items: list[str]) -> dict[str, Any]:
    result: dict[str, Any] = {}
    for item in items:
        if "=" not in item:
            raise ValueError(f"Expected field=value, received: {item}")
        key, value = item.split("=", 1)
        result[key] = value
    return result


def main() -> int:
    parser = argparse.ArgumentParser(description="BAP-controlled demo database client")
    parser.add_argument("operation", choices=["read", "write", "delete", "prod-read"])
    parser.add_argument("key", nargs="?", default="customer-123")
    parser.add_argument("assignments", nargs="*")
    parser.add_argument("--bap-session", required=True, help="Injected by the Claude Code PreToolUse hook")
    args = parser.parse_args()

    operation = "read" if args.operation == "prod-read" else args.operation
    payload: dict[str, Any] = {
        "session_id": args.bap_session,
        "operation": operation,
        "key": args.key,
    }
    if operation == "write":
        try:
            payload["value"] = parse_assignments(args.assignments)
        except ValueError as exc:
            print(json.dumps({"ok": False, "error": str(exc)}, indent=2))
            return 2

    try:
        connector_url = os.environ.get("BAP_CONNECTOR_URL", "http://127.0.0.1:8765").rstrip("/")
        status, result = json_request(f"{connector_url}/db/execute", payload, timeout=8)
    except Exception as exc:
        print(json.dumps({"ok": False, "error": f"Laptop connector unavailable: {exc}"}, indent=2))
        return 2
    print(json.dumps(result, indent=2, sort_keys=True))
    return 0 if status == 200 and result.get("ok") else 1


if __name__ == "__main__":
    raise SystemExit(main())
