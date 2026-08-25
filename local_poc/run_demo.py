from __future__ import annotations

import argparse
import os
import signal
import threading
import time
import webbrowser

from demo_common import EventBus, wait_for_url
from laptop_connector import LaptopConnectorState, build_connector_server
from mock_bap_server import MockBAPState, build_bap_server
from mock_db_server import MockDatabaseState, build_db_server


def main() -> int:
    parser = argparse.ArgumentParser(description="Run the laptop BAP demo services")
    parser.add_argument("--no-browser", action="store_true", help="Do not open the live dashboard")
    args = parser.parse_args()

    events = EventBus()
    db_state = MockDatabaseState(events)
    bap_state = MockBAPState(events)
    connector_state = LaptopConnectorState(events, db_state)

    servers = [
        build_bap_server("127.0.0.1", 8700, bap_state),
        build_db_server("127.0.0.1", 8800, db_state),
        build_connector_server("127.0.0.1", 8765, connector_state),
    ]
    threads: list[threading.Thread] = []
    for server in servers:
        thread = threading.Thread(target=server.serve_forever, daemon=True)
        thread.start()
        threads.append(thread)

    events.emit("DEMO", "SERVICES_READY", "Mock BAP listening on http://127.0.0.1:8700", {}, "success")
    events.emit("DEMO", "SERVICES_READY", "Laptop connector listening on http://127.0.0.1:8765", {}, "success")
    events.emit("DEMO", "SERVICES_READY", "Protected MockDB listening on http://127.0.0.1:8800", {}, "success")

    dashboard_url = "http://127.0.0.1:8765/"
    if not args.no_browser and wait_for_url("http://127.0.0.1:8765/health", 5):
        webbrowser.open(dashboard_url)

    print("\nLaptop BAP services are running.")
    print(f"Live dashboard: {dashboard_url}")
    print("Run Claude Code from this project folder in another terminal: claude")
    print("Press Ctrl+C or run stop-demo.bat to stop.\n")

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

