from __future__ import annotations

import json
import sys
import urllib.error
import urllib.request


def main() -> int:
    request = urllib.request.Request(
        "http://127.0.0.1:11600/query",
        data=json.dumps({"operation": "read", "key": "customer-123"}).encode(),
        headers={"Content-Type": "application/json"},
        method="POST",
    )
    try:
        with urllib.request.urlopen(request, timeout=3) as response:
            print(response.read().decode())
            return 0
    except urllib.error.HTTPError as error:
        print(error.read().decode())
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
