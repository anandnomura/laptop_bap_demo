from __future__ import annotations

from demo_common import json_request


if __name__ == "__main__":
    try:
        status, _ = json_request("http://127.0.0.1:8765/shutdown", {}, timeout=2)
        print("Laptop BAP demo stopped." if status == 200 else "Demo did not acknowledge shutdown.")
        raise SystemExit(0 if status == 200 else 1)
    except Exception:
        print("Laptop BAP demo is not running.")
        raise SystemExit(0)

