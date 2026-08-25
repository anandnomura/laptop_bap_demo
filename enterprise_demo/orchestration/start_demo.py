from __future__ import annotations

import argparse
import json
import os
import signal
import socket
import subprocess
import sys
import time
import webbrowser
from pathlib import Path
from typing import IO, Any


DEMO_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(DEMO_ROOT))

from common.http_json import request_json  # noqa: E402
from common.paths import (  # noqa: E402
    BAP_FRONT_DOOR_PORT,
    BAP_REPLICA_PORTS,
    DASHBOARD_PORT,
    LOG_ROOT,
    PID_FILE,
    PKI_ROOT,
    PROTECTED_RESOURCE_PORT,
    PFX_PASSWORD,
    REPO_ROOT,
    RESOURCE_GATEWAY_PORT,
    ensure_runtime,
)
from common.tls import mtls_client_context  # noqa: E402


SERVICES: list[tuple[str, list[str]]] = [
    (
        "protected-resource",
        [sys.executable, str(DEMO_ROOT / "protected_resource" / "app.py")],
    ),
    *[
        (
            f"bap-replica-{index + 1}",
            [
                sys.executable,
                str(DEMO_ROOT / "enterprise_bap" / "app.py"),
                "--port",
                str(port),
                "--replica-id",
                f"BAP REPLICA {index + 1}",
            ],
        )
        for index, port in enumerate(BAP_REPLICA_PORTS)
    ],
    (
        "bap-front-door",
        [sys.executable, str(DEMO_ROOT / "bap_front_door" / "app.py")],
    ),
    (
        "resource-gateway",
        [sys.executable, str(DEMO_ROOT / "resource_gateway" / "app.py")],
    ),
    (
        "central-dashboard",
        [sys.executable, str(DEMO_ROOT / "central_dashboard" / "app.py")],
    ),
    (
        "laptop-connector",
        [
            str(DEMO_ROOT / "laptop_connector_service" / "publish" / "bap_connector_service.exe"),
            "--client-pfx",
            str(PKI_ROOT / "connector-client.pfx"),
            "--pfx-password",
            PFX_PASSWORD,
            "--ca-cert",
            str(PKI_ROOT / "demo-ca.cert.pem"),
            "--require-signed-clients",
            "true",
        ],
    ),
]


def port_available(port: int) -> bool:
    with socket.socket() as probe:
        try:
            probe.bind(("127.0.0.1", port))
            return True
        except OSError:
            return False


def wait_http(url: str, ssl_context: Any = None, seconds: float = 12) -> None:
    deadline = time.time() + seconds
    last_error: Exception | None = None
    while time.time() < deadline:
        try:
            status, body = request_json(url, method="GET", timeout=1, ssl_context=ssl_context)
            if status == 200 and body.get("ok"):
                return
        except Exception as error:
            last_error = error
        time.sleep(0.2)
    raise RuntimeError(f"Service did not become ready at {url}: {last_error}")


def terminate(processes: list[tuple[str, subprocess.Popen[bytes], IO[bytes]]]) -> None:
    for _, process, _ in reversed(processes):
        if process.poll() is None:
            process.terminate()
    deadline = time.time() + 5
    for _, process, log in reversed(processes):
        if process.poll() is None:
            try:
                process.wait(max(0.1, deadline - time.time()))
            except subprocess.TimeoutExpired:
                process.kill()
        log.close()
    PID_FILE.unlink(missing_ok=True)


def main() -> int:
    parser = argparse.ArgumentParser(description="Start the production-shaped enterprise BAP demo")
    parser.add_argument("--no-browser", action="store_true")
    parser.add_argument("--preserve-state", action="store_true", help="Keep prior demo audit/grant state")
    arguments = parser.parse_args()
    ensure_runtime()
    required = [
        PKI_ROOT / "demo-ca.cert.pem",
        PKI_ROOT / "connector-client.pfx",
        DEMO_ROOT / "laptop_connector_service" / "publish" / "bap_connector_service.exe",
        DEMO_ROOT / "bap_resource_client" / "publish" / "bap_resource_client.exe",
        DEMO_ROOT / "claude_guard" / "publish" / "claude_guard.exe",
    ]
    missing = [str(path) for path in required if not path.exists()]
    if missing:
        print("Enterprise demo prerequisites are missing:\n  " + "\n  ".join(missing), file=sys.stderr)
        print("Run enterprise_demo\\orchestration\\build_demo.ps1 first.", file=sys.stderr)
        return 2

    ports = [BAP_FRONT_DOOR_PORT, RESOURCE_GATEWAY_PORT, DASHBOARD_PORT, *BAP_REPLICA_PORTS, PROTECTED_RESOURCE_PORT]
    unavailable = [port for port in ports if not port_available(port)]
    if unavailable:
        print(f"Cannot start: ports already in use: {unavailable}", file=sys.stderr)
        return 2

    if not arguments.preserve_state:
        from common.paths import STATE_DB

        for database_file in (STATE_DB, Path(str(STATE_DB) + "-wal"), Path(str(STATE_DB) + "-shm")):
            database_file.unlink(missing_ok=True)

    processes: list[tuple[str, subprocess.Popen[bytes], IO[bytes]]] = []
    try:
        for name, command in SERVICES:
            log = open(LOG_ROOT / f"{name}.log", "wb")
            process = subprocess.Popen(
                command,
                cwd=REPO_ROOT,
                stdin=subprocess.DEVNULL,
                stdout=log,
                stderr=subprocess.STDOUT,
                creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0),
            )
            processes.append((name, process, log))

        PID_FILE.write_text(
            json.dumps(
                {
                    "supervisor_pid": os.getpid(),
                    "services": [
                        {"name": name, "pid": process.pid, "command": command}
                        for (name, command), (_, process, _) in zip(SERVICES, processes, strict=True)
                    ],
                },
                indent=2,
            ),
            encoding="utf-8",
        )

        for port in BAP_REPLICA_PORTS:
            wait_http(f"http://127.0.0.1:{port}/health")
        wait_http(f"http://127.0.0.1:{PROTECTED_RESOURCE_PORT}/health")
        wait_http(f"http://127.0.0.1:{DASHBOARD_PORT}/health")
        mtls = mtls_client_context(
            PKI_ROOT / "connector-client.cert.pem",
            PKI_ROOT / "connector-client.key.pem",
            PKI_ROOT / "demo-ca.cert.pem",
        )
        wait_http(f"https://127.0.0.1:{BAP_FRONT_DOOR_PORT}/health", mtls)
        wait_http(f"https://127.0.0.1:{RESOURCE_GATEWAY_PORT}/health", mtls)
        guard = DEMO_ROOT / "claude_guard" / "publish" / "claude_guard.exe"
        deadline = time.time() + 10
        while time.time() < deadline:
            health = subprocess.run([guard, "--health"], capture_output=True, text=True, check=False)
            if health.returncode == 0:
                break
            time.sleep(0.25)
        else:
            raise RuntimeError(f"Named-pipe connector failed health check: {health.stderr}")

        dashboard = f"http://127.0.0.1:{DASHBOARD_PORT}/"
        print("\nEnterprise BAP demo is ready.")
        print("  ClaudeGuard -> named pipe -> laptop connector")
        print(f"  BAP mTLS front door: https://127.0.0.1:{BAP_FRONT_DOOR_PORT}")
        print(f"  Resource mTLS gateway: https://127.0.0.1:{RESOURCE_GATEWAY_PORT}")
        print(f"  Central evidence dashboard: {dashboard}")
        print("  Port 11022 is not used.")
        print("\nRun the smoke test or start Claude in another terminal.")
        print("Press Ctrl+C to stop every enterprise-demo service.\n")
        if not arguments.no_browser:
            webbrowser.open(dashboard)

        stop_requested = False

        def stop(_signum: int, _frame: object) -> None:
            nonlocal stop_requested
            stop_requested = True

        signal.signal(signal.SIGINT, stop)
        if hasattr(signal, "SIGTERM"):
            signal.signal(signal.SIGTERM, stop)
        while not stop_requested:
            failed = [(name, process.returncode) for name, process, _ in processes if process.poll() is not None]
            if failed:
                raise RuntimeError(f"Enterprise demo service exited unexpectedly: {failed}")
            time.sleep(0.5)
        return 0
    except Exception as error:
        print(f"Enterprise demo failed: {error}", file=sys.stderr)
        return 1
    finally:
        terminate(processes)


if __name__ == "__main__":
    raise SystemExit(main())
