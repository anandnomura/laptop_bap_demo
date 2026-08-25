from __future__ import annotations

import subprocess
import sys
import threading
from pathlib import Path

from demo_common import json_request
from python_agent_smoke_test import build_fake_llm, free_port


ROOT = Path(__file__).resolve().parent
CONNECTOR_URL = "http://127.0.0.1:8765"


def main() -> int:
    status, health = json_request(f"{CONNECTOR_URL}/health", method="GET", timeout=2)
    if status != 200 or not health.get("ok"):
        print("The live POC is not running. Start `py -3 run_demo.py` first.", file=sys.stderr)
        return 2

    llm_port = free_port()
    fake_llm = build_fake_llm(llm_port)
    thread = threading.Thread(target=fake_llm.serve_forever, daemon=True)
    thread.start()
    try:
        result = subprocess.run(
            [
                sys.executable,
                ROOT / "python_agent.py",
                "Read customer-123 and report its status",
                "--connector-url",
                CONNECTOR_URL,
                "--llm-url",
                f"http://127.0.0.1:{llm_port}/v1/chat/completions",
                "--model",
                "deterministic-demo-model",
            ],
            cwd=ROOT,
            text=True,
            capture_output=True,
            check=False,
        )
        if result.returncode != 0:
            print(result.stdout, end="")
            print(result.stderr, file=sys.stderr, end="")
            return result.returncode
        print(result.stdout, end="")
        print("LIVE PYTHON AGENT DEMO PASSED")
        print("  Watch http://127.0.0.1:8765 for the agent lifecycle and BAP evidence.")
        return 0
    finally:
        fake_llm.shutdown()
        fake_llm.server_close()
        thread.join(timeout=2)


if __name__ == "__main__":
    raise SystemExit(main())
