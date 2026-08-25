from __future__ import annotations

from demo_common import wait_for_url


if __name__ == "__main__":
    raise SystemExit(0 if wait_for_url("http://127.0.0.1:8765/health", 15) else 1)

