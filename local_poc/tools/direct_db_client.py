from __future__ import annotations

import json
import sys
from pathlib import Path


PROJECT_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(PROJECT_ROOT))

from demo_common import json_request  # noqa: E402


def main() -> int:
    status, result = json_request(
        "http://127.0.0.1:8800/query",
        {"operation": "read", "key": "customer-123"},
        timeout=3,
    )
    print(json.dumps(result, indent=2))
    return 0 if status == 200 else 1


if __name__ == "__main__":
    raise SystemExit(main())

