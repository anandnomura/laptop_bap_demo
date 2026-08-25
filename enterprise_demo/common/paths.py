from __future__ import annotations

from pathlib import Path


DEMO_ROOT = Path(__file__).resolve().parents[1]
REPO_ROOT = DEMO_ROOT.parent
RUNTIME_ROOT = DEMO_ROOT / "runtime"
PKI_ROOT = RUNTIME_ROOT / "pki"
LOG_ROOT = RUNTIME_ROOT / "logs"
STATE_DB = RUNTIME_ROOT / "enterprise-demo.db"
AUDIT_OUTBOX = RUNTIME_ROOT / "connector-audit-outbox.jsonl"
PID_FILE = RUNTIME_ROOT / "processes.json"

BAP_FRONT_DOOR_PORT = 11443
RESOURCE_GATEWAY_PORT = 11444
DASHBOARD_PORT = 11445
BAP_REPLICA_PORTS = (11501, 11502)
PROTECTED_RESOURCE_PORT = 11600

PIPE_NAME = "Company.BAP.Connector.v1"
PFX_PASSWORD = "demo-only-change-me"


def ensure_runtime() -> None:
    for directory in (RUNTIME_ROOT, PKI_ROOT, LOG_ROOT):
        directory.mkdir(parents=True, exist_ok=True)
