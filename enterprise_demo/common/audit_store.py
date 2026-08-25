from __future__ import annotations

import hashlib
import json
import re
import secrets
import sqlite3
import threading
import time
from datetime import datetime, timezone
from pathlib import Path
from typing import Any


_schema_lock = threading.Lock()
_sensitive_key = re.compile(r"(authorization|password|passwd|secret|token|api[_-]?key|private[_-]?key)", re.I)


AUDIT_COLUMNS: dict[str, str] = {
    "event_id": "TEXT",
    "received_at_utc": "TEXT",
    "outcome": "TEXT",
    "trace_id": "TEXT",
    "request_id": "TEXT",
    "decision_id": "TEXT",
    "execution_id": "TEXT",
    "session_id": "TEXT",
    "agent_run_id": "TEXT",
    "user_id": "TEXT",
    "device_id": "TEXT",
    "agent_type": "TEXT",
    "agent_version": "TEXT",
    "tool_name": "TEXT",
    "task_summary": "TEXT",
    "action": "TEXT",
    "resource": "TEXT",
    "resource_key": "TEXT",
    "decision": "TEXT",
    "decision_reason": "TEXT",
    "policy_bundle_id": "TEXT",
    "policy_revision": "TEXT",
    "policy_rule_id": "TEXT",
    "policy_bundle_sha256": "TEXT",
    "approval_request_id": "TEXT",
    "approver_id": "TEXT",
    "grant_id": "TEXT",
    "grant_expires_at": "INTEGER",
    "http_status": "INTEGER",
    "client_process_id": "INTEGER",
    "client_executable": "TEXT",
    "client_signer_subject": "TEXT",
    "mtls_subject": "TEXT",
    "request_payload_hash": "TEXT",
    "result_payload_hash": "TEXT",
    "previous_event_hash": "TEXT",
    "event_hash": "TEXT",
}


class AuditStore:
    def __init__(self, database: Path) -> None:
        self.database = database
        self.database.parent.mkdir(parents=True, exist_ok=True)
        last_error: sqlite3.OperationalError | None = None
        for _attempt in range(50):
            try:
                with _schema_lock, self.connect() as connection:
                    self._initialize_schema(connection)
                return
            except sqlite3.OperationalError as error:
                last_error = error
                if "locked" not in str(error).lower():
                    raise
                time.sleep(0.1)
        raise last_error or sqlite3.OperationalError("Failed to initialize shared audit store")

    def _initialize_schema(self, connection: sqlite3.Connection) -> None:
        connection.executescript(
            """
            PRAGMA journal_mode=WAL;
            PRAGMA synchronous=FULL;

            CREATE TABLE IF NOT EXISTS audit_events (
                sequence INTEGER PRIMARY KEY AUTOINCREMENT,
                timestamp TEXT NOT NULL,
                source TEXT NOT NULL,
                kind TEXT NOT NULL,
                message TEXT NOT NULL,
                level TEXT NOT NULL,
                details_json TEXT NOT NULL
            );

            CREATE TABLE IF NOT EXISTS grants (
                grant_id TEXT PRIMARY KEY,
                token TEXT NOT NULL DEFAULT '',
                token_hash TEXT,
                agent_run TEXT NOT NULL,
                action TEXT NOT NULL,
                resource TEXT NOT NULL,
                expires_at INTEGER NOT NULL,
                approved_by TEXT NOT NULL,
                policy_rule_id TEXT NOT NULL DEFAULT 'legacy',
                policy_revision TEXT NOT NULL DEFAULT 'legacy',
                revoked INTEGER NOT NULL DEFAULT 0
            );

            CREATE TABLE IF NOT EXISTS approvals (
                request_id TEXT PRIMARY KEY,
                user_id TEXT NOT NULL,
                agent_run TEXT NOT NULL,
                action TEXT NOT NULL,
                resource TEXT NOT NULL,
                policy_rule_id TEXT NOT NULL DEFAULT 'legacy',
                policy_revision TEXT NOT NULL DEFAULT 'legacy',
                grant_ttl_seconds INTEGER NOT NULL DEFAULT 60,
                request_json TEXT NOT NULL DEFAULT '{}',
                request_hash TEXT,
                status TEXT NOT NULL
            );
            """
        )
        for column, declaration in AUDIT_COLUMNS.items():
            self._add_column(connection, "audit_events", column, declaration)
        self._add_column(connection, "grants", "token_hash", "TEXT")
        self._add_column(connection, "grants", "policy_rule_id", "TEXT NOT NULL DEFAULT 'legacy'")
        self._add_column(connection, "grants", "policy_revision", "TEXT NOT NULL DEFAULT 'legacy'")
        self._add_column(connection, "approvals", "policy_rule_id", "TEXT NOT NULL DEFAULT 'legacy'")
        self._add_column(connection, "approvals", "policy_revision", "TEXT NOT NULL DEFAULT 'legacy'")
        self._add_column(connection, "approvals", "grant_ttl_seconds", "INTEGER NOT NULL DEFAULT 60")
        self._add_column(connection, "approvals", "request_json", "TEXT NOT NULL DEFAULT '{}'")
        self._add_column(connection, "approvals", "request_hash", "TEXT")
        connection.execute("UPDATE grants SET token_hash=lower(hex(sha3(token,256))), token='' WHERE token<>''") if self._has_sha3(connection) else connection.execute("UPDATE grants SET token='' WHERE token<>''")
        needs_backfill = connection.execute(
            "SELECT 1 FROM audit_events WHERE event_id IS NULL OR event_hash IS NULL LIMIT 1"
        ).fetchone()
        if needs_backfill:
            # This is a one-time legacy migration. Normal service starts never remove
            # the append-only controls.
            connection.executescript(
                "DROP TRIGGER IF EXISTS audit_events_no_update;"
                "DROP TRIGGER IF EXISTS audit_events_no_delete;"
            )
            self._backfill_chain(connection)
        connection.executescript(
            """
            CREATE UNIQUE INDEX IF NOT EXISTS idx_audit_event_id ON audit_events(event_id);
            CREATE INDEX IF NOT EXISTS idx_audit_time ON audit_events(timestamp);
            CREATE INDEX IF NOT EXISTS idx_audit_trace ON audit_events(trace_id, sequence);
            CREATE INDEX IF NOT EXISTS idx_audit_request ON audit_events(request_id, sequence);
            CREATE INDEX IF NOT EXISTS idx_audit_agent_run ON audit_events(agent_run_id, sequence);
            CREATE INDEX IF NOT EXISTS idx_audit_user_time ON audit_events(user_id, timestamp);
            CREATE INDEX IF NOT EXISTS idx_audit_resource_time ON audit_events(resource, timestamp);
            CREATE INDEX IF NOT EXISTS idx_audit_decision_time ON audit_events(decision, timestamp);
            CREATE INDEX IF NOT EXISTS idx_audit_grant ON audit_events(grant_id, sequence);
            CREATE INDEX IF NOT EXISTS idx_audit_execution ON audit_events(execution_id, sequence);
            CREATE INDEX IF NOT EXISTS idx_audit_kind_time ON audit_events(kind, timestamp);

            DROP VIEW IF EXISTS access_audit_view;
            CREATE VIEW access_audit_view AS
            SELECT
                request_id,
                MAX(trace_id) AS trace_id,
                MIN(timestamp) AS requested_at_utc,
                MAX(timestamp) AS last_event_at_utc,
                MAX(user_id) AS user_id,
                MAX(device_id) AS device_id,
                MAX(agent_type) AS agent_type,
                MAX(agent_run_id) AS agent_run_id,
                MAX(session_id) AS session_id,
                MAX(task_summary) AS task_summary,
                MAX(action) AS action,
                MAX(resource) AS resource,
                MAX(resource_key) AS resource_key,
                (SELECT decision FROM audit_events d WHERE d.request_id=e.request_id AND d.kind='AUTHORIZATION_DECISION' ORDER BY d.sequence DESC LIMIT 1) AS decision,
                (SELECT decision_reason FROM audit_events d WHERE d.request_id=e.request_id AND d.kind='AUTHORIZATION_DECISION' ORDER BY d.sequence DESC LIMIT 1) AS decision_reason,
                (SELECT policy_rule_id FROM audit_events d WHERE d.request_id=e.request_id AND d.policy_rule_id IS NOT NULL ORDER BY d.sequence DESC LIMIT 1) AS policy_rule_id,
                (SELECT policy_revision FROM audit_events d WHERE d.request_id=e.request_id AND d.policy_revision IS NOT NULL ORDER BY d.sequence DESC LIMIT 1) AS policy_revision,
                MAX(approval_request_id) AS approval_request_id,
                MAX(approver_id) AS approver_id,
                MAX(grant_id) AS grant_id,
                MAX(execution_id) AS execution_id,
                CASE
                    WHEN EXISTS(SELECT 1 FROM audit_events x WHERE x.request_id=e.request_id AND x.kind IN ('RESOURCE_EXECUTED','EXECUTION_RESULT') AND x.outcome IN ('SUCCEEDED','EXECUTED')) THEN 'EXECUTED'
                    WHEN EXISTS(SELECT 1 FROM audit_events x WHERE x.request_id=e.request_id AND x.kind IN ('EXECUTION_DENIED','RESOURCE_RESULT_DENIED')) THEN 'DENIED'
                    ELSE 'NOT_EXECUTED'
                END AS execution_outcome,
                (SELECT http_status FROM audit_events x WHERE x.request_id=e.request_id AND x.http_status IS NOT NULL ORDER BY x.sequence DESC LIMIT 1) AS final_http_status
            FROM audit_events e
            WHERE request_id IS NOT NULL AND request_id<>''
              AND EXISTS (SELECT 1 FROM audit_events q WHERE q.request_id=e.request_id AND q.action IS NOT NULL)
            GROUP BY request_id;

            CREATE TRIGGER IF NOT EXISTS audit_events_no_update
            BEFORE UPDATE ON audit_events
            BEGIN
                SELECT RAISE(ABORT, 'audit_events is append-only');
            END;

            CREATE TRIGGER IF NOT EXISTS audit_events_no_delete
            BEFORE DELETE ON audit_events
            BEGIN
                SELECT RAISE(ABORT, 'audit_events is append-only');
            END;
            """
        )

    @staticmethod
    def _has_sha3(connection: sqlite3.Connection) -> bool:
        try:
            connection.execute("SELECT sha3('test',256)").fetchone()
            return True
        except sqlite3.OperationalError:
            return False

    @staticmethod
    def _add_column(connection: sqlite3.Connection, table: str, column: str, declaration: str) -> None:
        existing = {row[1] for row in connection.execute(f"PRAGMA table_info({table})")}
        if column not in existing:
            try:
                connection.execute(f"ALTER TABLE {table} ADD COLUMN {column} {declaration}")
            except sqlite3.OperationalError as error:
                # Another process may complete the same idempotent migration after
                # PRAGMA table_info and before ALTER TABLE.
                if "duplicate column name" not in str(error).lower():
                    raise

    def _backfill_chain(self, connection: sqlite3.Connection) -> None:
        previous = "GENESIS"
        rows = connection.execute("SELECT * FROM audit_events ORDER BY sequence").fetchall()
        for row in rows:
            value = dict(row)
            event_id = value.get("event_id") or "evt-" + secrets.token_hex(16)
            received = value.get("received_at_utc") or value["timestamp"]
            normalized = {
                **value,
                "event_id": event_id,
                "received_at_utc": received,
                "previous_event_hash": previous,
            }
            normalized.pop("event_hash", None)
            event_hash = self._hash(normalized)
            connection.execute(
                "UPDATE audit_events SET event_id=?,received_at_utc=?,previous_event_hash=?,event_hash=? WHERE sequence=?",
                (event_id, received, previous, event_hash, value["sequence"]),
            )
            previous = event_hash

    def connect(self) -> sqlite3.Connection:
        connection = sqlite3.connect(self.database, timeout=15)
        connection.row_factory = sqlite3.Row
        connection.execute("PRAGMA busy_timeout=15000")
        return connection

    def emit(
        self,
        source: str,
        kind: str,
        message: str,
        details: dict[str, Any] | None = None,
        level: str = "info",
    ) -> str:
        event_time = datetime.now(timezone.utc).isoformat(timespec="milliseconds").replace("+00:00", "Z")
        original_details = details or {}
        sanitized = self.redact(original_details)
        assert isinstance(sanitized, dict)
        fields = self._extract_fields(sanitized)
        event_id = "evt-" + secrets.token_hex(16)
        row: dict[str, Any] = {
            "event_id": event_id,
            "timestamp": event_time,
            "received_at_utc": event_time,
            "source": source[:80],
            "kind": kind[:80],
            "message": message[:1000],
            "level": level if level in {"info", "success", "warning", "error"} else "info",
            "details_json": json.dumps(sanitized, sort_keys=True, separators=(",", ":")),
            **fields,
        }
        columns = [
            "event_id", "timestamp", "received_at_utc", "source", "kind", "message", "level",
            "details_json", *[name for name in AUDIT_COLUMNS if name not in {"event_id", "received_at_utc", "previous_event_hash", "event_hash"}],
            "previous_event_hash", "event_hash",
        ]
        with self.connect() as connection:
            connection.isolation_level = None
            connection.execute("BEGIN IMMEDIATE")
            try:
                previous_row = connection.execute(
                    "SELECT event_hash FROM audit_events ORDER BY sequence DESC LIMIT 1"
                ).fetchone()
                row["previous_event_hash"] = previous_row["event_hash"] if previous_row else "GENESIS"
                row["event_hash"] = self._hash(row)
                placeholders = ",".join("?" for _ in columns)
                connection.execute(
                    f"INSERT INTO audit_events({','.join(columns)}) VALUES({placeholders})",
                    [row.get(column) for column in columns],
                )
                connection.execute("COMMIT")
            except Exception:
                connection.execute("ROLLBACK")
                raise
        print(f"[{event_time[11:23]}] [{source}] [{kind}] {message}", flush=True)
        return event_id

    @classmethod
    def _extract_fields(cls, details: dict[str, Any]) -> dict[str, Any]:
        claims = details.get("claims") if isinstance(details.get("claims"), dict) else {}
        client = details.get("client") if isinstance(details.get("client"), dict) else {}
        policy = details.get("policy") if isinstance(details.get("policy"), dict) else {}

        def pick(*names: str, containers: tuple[dict[str, Any], ...] = (details, claims)) -> Any:
            for container in containers:
                for name in names:
                    value = container.get(name)
                    if value not in (None, ""):
                        return value
            return None

        return {
            "outcome": pick("outcome"),
            "trace_id": pick("trace_id"),
            "request_id": pick("request_id"),
            "decision_id": pick("decision_id"),
            "execution_id": pick("execution_id"),
            "session_id": pick("session_id"),
            "agent_run_id": pick("agent_run_id", "agent_run"),
            "user_id": pick("user_id", "user", "sub"),
            "device_id": pick("device_id", "device"),
            "agent_type": pick("agent_type", "agent"),
            "agent_version": pick("agent_version"),
            "tool_name": pick("tool_name"),
            "task_summary": pick("task_summary", "task"),
            "action": pick("action"),
            "resource": pick("resource"),
            "resource_key": pick("resource_key", "key"),
            "decision": pick("decision", "effect"),
            "decision_reason": pick("decision_reason", "reason"),
            "policy_bundle_id": pick("policy_bundle_id", "bundle_id", containers=(details, claims, policy)),
            "policy_revision": pick("policy_revision", "revision", containers=(details, claims, policy)),
            "policy_rule_id": pick("policy_rule_id", "rule_id", containers=(details, claims, policy)),
            "policy_bundle_sha256": pick("policy_bundle_sha256", "bundle_sha256", containers=(details, claims, policy)),
            "approval_request_id": pick("approval_request_id"),
            "approver_id": pick("approver_id", "approved_by"),
            "grant_id": pick("grant_id"),
            "grant_expires_at": pick("grant_expires_at", "expires_at", "exp"),
            "http_status": pick("http_status"),
            "client_process_id": pick("client_process_id", containers=(details, client)),
            "client_executable": pick("client_executable", containers=(details, client)),
            "client_signer_subject": pick("client_signer_subject", containers=(details, client)),
            "mtls_subject": pick("mtls_subject", "mtls_client"),
            "request_payload_hash": pick("request_payload_hash"),
            "result_payload_hash": pick("result_payload_hash"),
        }

    @classmethod
    def redact(cls, value: Any, depth: int = 0) -> Any:
        if depth > 8:
            return "[MAX_DEPTH]"
        if isinstance(value, dict):
            return {
                str(key)[:120]: "[REDACTED]" if _sensitive_key.search(str(key)) else cls.redact(item, depth + 1)
                for key, item in value.items()
            }
        if isinstance(value, list):
            return [cls.redact(item, depth + 1) for item in value[:100]]
        if isinstance(value, str):
            return value[:4000]
        if value is None or isinstance(value, (bool, int, float)):
            return value
        return str(value)[:4000]

    @staticmethod
    def payload_hash(value: Any) -> str:
        encoded = json.dumps(value, sort_keys=True, separators=(",", ":"), default=str).encode()
        return hashlib.sha256(encoded).hexdigest()

    @staticmethod
    def _hash(value: dict[str, Any]) -> str:
        canonical = {key: item for key, item in value.items() if key not in {"sequence", "event_hash"}}
        encoded = json.dumps(canonical, sort_keys=True, separators=(",", ":"), default=str).encode()
        return hashlib.sha256(encoded).hexdigest()

    def search_events(self, filters: dict[str, Any], limit: int = 200, offset: int = 0) -> list[dict[str, Any]]:
        allowed = {
            "event_id", "trace_id", "request_id", "decision_id", "execution_id", "session_id",
            "agent_run_id", "user_id", "device_id", "agent_type", "action", "resource", "decision",
            "policy_rule_id", "approval_request_id", "grant_id", "kind", "source", "outcome",
        }
        clauses: list[str] = []
        values: list[Any] = []
        for key, value in filters.items():
            if key in allowed and value not in (None, ""):
                clauses.append(f"{key}=?")
                values.append(value)
        if filters.get("from"):
            clauses.append("timestamp>=?")
            values.append(filters["from"])
        if filters.get("to"):
            clauses.append("timestamp<=?")
            values.append(filters["to"])
        where = " WHERE " + " AND ".join(clauses) if clauses else ""
        values.extend([max(1, min(limit, 1000)), max(0, offset)])
        with self.connect() as connection:
            rows = connection.execute(
                f"SELECT * FROM audit_events{where} ORDER BY sequence DESC LIMIT ? OFFSET ?", values
            ).fetchall()
        return [self._public_event(dict(row)) for row in rows]

    def search_access(self, filters: dict[str, Any], limit: int = 200) -> list[dict[str, Any]]:
        allowed = {"request_id", "trace_id", "session_id", "user_id", "device_id", "agent_type", "agent_run_id", "action", "resource", "decision", "policy_rule_id", "grant_id", "execution_id", "execution_outcome"}
        clauses: list[str] = []
        values: list[Any] = []
        for key, value in filters.items():
            if key in allowed and value not in (None, ""):
                clauses.append(f"{key}=?")
                values.append(value)
        where = " WHERE " + " AND ".join(clauses) if clauses else ""
        values.append(max(1, min(limit, 1000)))
        with self.connect() as connection:
            rows = connection.execute(
                f"SELECT * FROM access_audit_view{where} ORDER BY requested_at_utc DESC LIMIT ?", values
            ).fetchall()
        return [dict(row) for row in rows]

    def verify_chain(self) -> dict[str, Any]:
        previous = "GENESIS"
        checked = 0
        with self.connect() as connection:
            rows = connection.execute("SELECT * FROM audit_events ORDER BY sequence").fetchall()
        for row in rows:
            value = dict(row)
            recorded_hash = value.pop("event_hash")
            if value.get("previous_event_hash") != previous:
                return {"ok": False, "checked": checked, "sequence": value["sequence"], "reason": "previous hash mismatch"}
            calculated = self._hash(value)
            if calculated != recorded_hash:
                return {"ok": False, "checked": checked, "sequence": value["sequence"], "reason": "event hash mismatch"}
            previous = recorded_hash
            checked += 1
        return {"ok": True, "checked": checked, "head_hash": previous}

    @staticmethod
    def _public_event(row: dict[str, Any]) -> dict[str, Any]:
        row["details"] = json.loads(row.pop("details_json", "{}"))
        return row

    def snapshot(self, limit: int = 300) -> dict[str, Any]:
        events = list(reversed(self.search_events({}, limit=limit)))
        with self.connect() as connection:
            grants = [
                {key: value for key, value in dict(row).items() if key not in {"token", "token_hash"}}
                for row in connection.execute("SELECT * FROM grants ORDER BY rowid DESC LIMIT 50").fetchall()
            ]
            approvals = []
            for row in connection.execute("SELECT * FROM approvals ORDER BY rowid DESC LIMIT 50").fetchall():
                item = dict(row)
                raw = item.pop("request_json", "{}")
                try:
                    item["request_context"] = json.loads(raw)
                except json.JSONDecodeError:
                    item["request_context"] = "[INVALID]"
                approvals.append(item)
        return {
            "events": events,
            "grants": grants,
            "approvals": approvals,
            "access": self.search_access({}, limit=50),
            "integrity": self.verify_chain(),
        }
