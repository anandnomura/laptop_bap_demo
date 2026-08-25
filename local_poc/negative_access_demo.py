from __future__ import annotations

import argparse
import json
import os
import secrets
from typing import Any

from demo_common import json_request


def post(connector_url: str, path: str, payload: dict[str, Any]) -> tuple[int, dict[str, Any]]:
    return json_request(f"{connector_url.rstrip('/')}{path}", payload, timeout=8)


def main() -> int:
    parser = argparse.ArgumentParser(description="Demonstrate BAP denial without a grant and with a fictitious grant")
    parser.add_argument(
        "--connector-url",
        default=os.environ.get("BAP_CONNECTOR_URL", "http://127.0.0.1:8765"),
    )
    args = parser.parse_args()

    _, before = json_request(f"{args.connector_url.rstrip('/')}/api/state", method="GET", timeout=5)
    before_sequence = max((int(event["sequence"]) for event in before.get("events", [])), default=0)

    no_grant_status, no_grant = post(
        args.connector_url,
        "/db/execute",
        {
            "session_id": "unregistered-" + secrets.token_hex(4),
            "operation": "read",
            "key": "customer-123",
        },
    )
    fake_token = "eyJhbGciOiJIUzI1NiJ9.eyJncmFudF9pZCI6ImZha2UifQ.ZmljdGl0aW91cw"
    fake_grant_status, fake_grant = post(
        args.connector_url,
        "/demo/external-grant-attempt",
        {
            "token": fake_token,
            "action": "database.read",
            "resource": "dev-customer-db",
            "agent_run": "fictitious-run-" + secrets.token_hex(4),
        },
    )

    _, after = json_request(f"{args.connector_url.rstrip('/')}/api/state", method="GET", timeout=5)
    new_events = [event for event in after.get("events", []) if int(event["sequence"]) > before_sequence]
    kinds = [str(event.get("kind")) for event in new_events]
    passed = (
        no_grant_status == 403
        and fake_grant_status == 403
        and no_grant.get("ok") is False
        and fake_grant.get("ok") is False
        and fake_grant.get("forwarded_to_database") is False
        and "NO_GRANT_DENIED" in kinds
        and "FICTITIOUS_GRANT_DENIED" in kinds
        and "QUERY_EXECUTED" not in kinds
    )
    print(
        json.dumps(
            {
                "passed": passed,
                "without_grant": {"http_status": no_grant_status, "response": no_grant},
                "fictitious_grant": {"http_status": fake_grant_status, "response": fake_grant},
                "dashboard_events": kinds,
                "database_query_executed": "QUERY_EXECUTED" in kinds,
            },
            indent=2,
        )
    )
    return 0 if passed else 1


if __name__ == "__main__":
    raise SystemExit(main())
