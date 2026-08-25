from __future__ import annotations

import json
import socket
import subprocess
import sys
import threading
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path

from demo_common import EventBus
from laptop_connector import LaptopConnectorState, build_connector_server
from mock_bap_server import MockBAPState, build_bap_server
from mock_db_server import MockDatabaseState, build_db_server


ROOT = Path(__file__).resolve().parent


def free_port() -> int:
    with socket.socket() as sock:
        sock.bind(("127.0.0.1", 0))
        return int(sock.getsockname()[1])


def build_fake_llm(port: int) -> ThreadingHTTPServer:
    class Handler(BaseHTTPRequestHandler):
        calls = 0

        def log_message(self, _format: str, *_args: object) -> None:
            return

        def do_POST(self) -> None:
            length = int(self.headers.get("Content-Length", "0"))
            json.loads(self.rfile.read(length) or b"{}")
            Handler.calls += 1
            content = (
                '{"operation":"read","key":"customer-123","reason":"Inspect the requested status"}'
                if Handler.calls == 1
                else "Customer customer-123 is active."
            )
            body = json.dumps({"choices": [{"message": {"role": "assistant", "content": content}}]}).encode()
            self.send_response(200)
            self.send_header("Content-Type", "application/json")
            self.send_header("Content-Length", str(len(body)))
            self.end_headers()
            self.wfile.write(body)

    return ThreadingHTTPServer(("127.0.0.1", port), Handler)


def main() -> int:
    bap_port, db_port, connector_port, llm_port = (free_port() for _ in range(4))
    events = EventBus()
    db_state = MockDatabaseState(events)
    bap_state = MockBAPState(events)
    connector_state = LaptopConnectorState(
        events,
        db_state,
        bap_url=f"http://127.0.0.1:{bap_port}",
        db_url=f"http://127.0.0.1:{db_port}",
    )
    servers = [
        build_bap_server("127.0.0.1", bap_port, bap_state),
        build_db_server("127.0.0.1", db_port, db_state),
        build_connector_server("127.0.0.1", connector_port, connector_state),
        build_fake_llm(llm_port),
    ]
    threads = [threading.Thread(target=server.serve_forever, daemon=True) for server in servers]
    for thread in threads:
        thread.start()

    try:
        result = subprocess.run(
            [
                sys.executable,
                str(ROOT / "python_agent.py"),
                "Read customer-123 and report its status",
                "--connector-url",
                f"http://127.0.0.1:{connector_port}",
                "--llm-url",
                f"http://127.0.0.1:{llm_port}/v1/chat/completions",
                "--model",
                "fake-local-model",
            ],
            cwd=ROOT,
            text=True,
            capture_output=True,
            check=False,
        )
        assert result.returncode == 0, result.stdout + result.stderr
        output = json.loads(result.stdout)
        assert output["session"]["agent"] == "local-llm-python-agent"
        assert output["session"]["agent_run"].startswith("py-run-")
        assert output["proposal"]["operation"] == "read"
        assert output["result"]["record"]["name"] == "Ada"
        assert output["result"]["bap_evidence"]["agent_run"].startswith("py-run-")
        kinds = [event["kind"] for event in events.snapshot()]
        for expected in (
            "SESSION_START",
            "TASK_INTENT",
            "LLM_PROPOSAL",
            "TOOL_INTERCEPTED",
            "GRANT_ISSUED",
            "GRANT_VALID",
            "QUERY_EXECUTED",
            "ACTUAL_RESULT",
            "FINAL_RESPONSE",
            "SESSION_END",
        ):
            assert expected in kinds, f"Missing dashboard event {expected}: {kinds}"
        print("PYTHON AGENT SMOKE TEST PASSED")
        print("  [PASS] Local LLM selected a bounded read action")
        print("  [PASS] Connector registered a distinct Python agent run")
        print("  [PASS] BAP grant controlled and correlated the database read")
        print("  [PASS] Dashboard captured the complete agent lifecycle")
        return 0
    finally:
        for server in servers:
            server.shutdown()
            server.server_close()
        for thread in threads:
            thread.join(timeout=2)


if __name__ == "__main__":
    raise SystemExit(main())
