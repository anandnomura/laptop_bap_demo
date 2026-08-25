from __future__ import annotations

import argparse
import json
import ssl
import sys
import threading
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from urllib.parse import urlparse


DEMO_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(DEMO_ROOT))

from common.audit_store import AuditStore  # noqa: E402
from common.http_json import request_json  # noqa: E402
from common.paths import (  # noqa: E402
    BAP_FRONT_DOOR_PORT,
    BAP_REPLICA_PORTS,
    PKI_ROOT,
    STATE_DB,
    ensure_runtime,
)
from common.tls import mtls_server_context  # noqa: E402


class ReplicaPool:
    def __init__(self) -> None:
        self._index = 0
        self._lock = threading.Lock()

    def next(self) -> int:
        with self._lock:
            port = BAP_REPLICA_PORTS[self._index % len(BAP_REPLICA_PORTS)]
            self._index += 1
            return port


def peer_subject(connection: ssl.SSLSocket) -> str:
    certificate = connection.getpeercert()
    parts = []
    for relative_name in certificate.get("subject", []):
        for key, value in relative_name:
            parts.append(f"{key}={value}")
    return ",".join(parts) or "unknown-client"


def build_server(port: int, store: AuditStore) -> ThreadingHTTPServer:
    pool = ReplicaPool()

    class Handler(BaseHTTPRequestHandler):
        def log_message(self, _format: str, *_args: object) -> None:
            return

        def send_json(self, status: int, value: dict) -> None:
            body = json.dumps(value).encode()
            self.send_response(status)
            self.send_header("Content-Type", "application/json")
            self.send_header("Content-Length", str(len(body)))
            self.end_headers()
            self.wfile.write(body)

        def proxy(self, method: str) -> None:
            path = urlparse(self.path).path
            body = None
            if method == "POST":
                length = int(self.headers.get("Content-Length", "0"))
                body = json.loads(self.rfile.read(length) or b"{}")
            client_subject = peer_subject(self.connection)
            replica_port = pool.next()
            store.emit(
                "BAP FRONT DOOR",
                "MTLS_ACCEPTED",
                f"Authenticated connector and routed {path} to replica :{replica_port}",
                {"client_subject": client_subject, "replica_port": replica_port, "path": path},
                "success",
            )
            try:
                status, result = request_json(
                    f"http://127.0.0.1:{replica_port}{path}",
                    body,
                    method=method,
                    headers={"X-Demo-mTLS-Client": client_subject},
                )
            except Exception as error:
                status, result = 503, {"error": f"BAP replica unavailable: {error}"}
            self.send_json(status, result)

        def do_GET(self) -> None:
            self.proxy("GET")

        def do_POST(self) -> None:
            self.proxy("POST")

    server = ThreadingHTTPServer(("127.0.0.1", port), Handler)
    context = mtls_server_context(
        PKI_ROOT / "bap-front-door.cert.pem",
        PKI_ROOT / "bap-front-door.key.pem",
        PKI_ROOT / "demo-ca.cert.pem",
    )
    server.socket = context.wrap_socket(server.socket, server_side=True)
    return server


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--port", type=int, default=BAP_FRONT_DOOR_PORT)
    arguments = parser.parse_args()
    ensure_runtime()
    store = AuditStore(STATE_DB)
    store.emit("BAP FRONT DOOR", "SERVICE_READY", f"mTLS front door listening on 127.0.0.1:{arguments.port}")
    build_server(arguments.port, store).serve_forever()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
