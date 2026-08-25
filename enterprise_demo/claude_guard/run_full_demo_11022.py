from __future__ import annotations

import signal
import sys
import threading
import webbrowser
from pathlib import Path


PROJECT_ROOT = Path(__file__).resolve().parents[2] / "local_poc"
sys.path.insert(0, str(PROJECT_ROOT))

from demo_common import EventBus, wait_for_url  # noqa: E402
from laptop_connector import LaptopConnectorState, build_connector_server  # noqa: E402
from mock_bap_server import MockBAPState, build_bap_server  # noqa: E402
from mock_db_server import MockDatabaseState, build_db_server  # noqa: E402


CONNECTOR_PORT = 11022


def main() -> int:
    events = EventBus()
    db_state = MockDatabaseState(events)
    bap_state = MockBAPState(events)
    connector_state = LaptopConnectorState(events, db_state)

    servers = [
        build_bap_server("127.0.0.1", 8700, bap_state),
        build_db_server("127.0.0.1", 8800, db_state),
        build_connector_server("127.0.0.1", CONNECTOR_PORT, connector_state),
    ]
    threads: list[threading.Thread] = []
    for server in servers:
        thread = threading.Thread(target=server.serve_forever, daemon=True)
        thread.start()
        threads.append(thread)

    connector_url = f"http://127.0.0.1:{CONNECTOR_PORT}"
    events.emit("DEMO", "SERVICES_READY", "Mock BAP listening on http://127.0.0.1:8700", {}, "success")
    events.emit("DEMO", "SERVICES_READY", f"Laptop connector listening on {connector_url}", {}, "success")
    events.emit("DEMO", "SERVICES_READY", "Protected MockDB listening on http://127.0.0.1:8800", {}, "success")

    if wait_for_url(f"{connector_url}/health", 5):
        webbrowser.open(f"{connector_url}/")

    print("\nFull laptop BAP demo is running with ClaudeGuard on port 11022.")
    print(f"Dashboard: {connector_url}/")
    print("Start Claude Code from the project root in another terminal.")
    print("Press Ctrl+C to stop.\n")

    def request_stop(_signum: int, _frame: object) -> None:
        connector_state.shutdown_event.set()

    signal.signal(signal.SIGINT, request_stop)
    if hasattr(signal, "SIGTERM"):
        signal.signal(signal.SIGTERM, request_stop)

    try:
        while not connector_state.shutdown_event.wait(0.5):
            pass
    finally:
        events.emit("DEMO", "SHUTDOWN", "Stopping all demo services", {}, "warning")
        for server in servers:
            server.shutdown()
            server.server_close()
        for thread in threads:
            thread.join(timeout=2)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
