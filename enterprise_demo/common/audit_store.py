from __future__ import annotations

import json
import sqlite3
import threading
import time
from datetime import datetime, timezone
from pathlib import Path
from typing import Any


_schema_lock = threading.Lock()


class AuditStore:
    def __init__(self, database: Path) -> None:
        self.database = database
        self.database.parent.mkdir(parents=True, exist_ok=True)
        last_error: sqlite3.OperationalError | None = None
        for _attempt in range(50):
            try:
                with _schema_lock, self.connect() as connection:
                    connection.executescript(
                """
                PRAGMA journal_mode=WAL;
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
                    token TEXT NOT NULL,
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
                    status TEXT NOT NULL
                );
                """
                    )
                    self._add_column(connection, "grants", "policy_rule_id", "TEXT NOT NULL DEFAULT 'legacy'")
                    self._add_column(connection, "grants", "policy_revision", "TEXT NOT NULL DEFAULT 'legacy'")
                    self._add_column(connection, "approvals", "policy_rule_id", "TEXT NOT NULL DEFAULT 'legacy'")
                    self._add_column(connection, "approvals", "policy_revision", "TEXT NOT NULL DEFAULT 'legacy'")
                    self._add_column(connection, "approvals", "grant_ttl_seconds", "INTEGER NOT NULL DEFAULT 60")
                    self._add_column(connection, "approvals", "request_json", "TEXT NOT NULL DEFAULT '{}'")
                return
            except sqlite3.OperationalError as error:
                last_error = error
                if "locked" not in str(error).lower():
                    raise
                time.sleep(0.1)
        raise last_error or sqlite3.OperationalError("Failed to initialize shared audit store")

    @staticmethod
    def _add_column(connection: sqlite3.Connection, table: str, column: str, declaration: str) -> None:
        existing = {row[1] for row in connection.execute(f"PRAGMA table_info({table})")}
        if column not in existing:
            connection.execute(f"ALTER TABLE {table} ADD COLUMN {column} {declaration}")

    def connect(self) -> sqlite3.Connection:
        connection = sqlite3.connect(self.database, timeout=10)
        connection.row_factory = sqlite3.Row
        connection.execute("PRAGMA busy_timeout=10000")
        return connection

    def emit(
        self,
        source: str,
        kind: str,
        message: str,
        details: dict[str, Any] | None = None,
        level: str = "info",
    ) -> None:
        timestamp = datetime.now(timezone.utc).astimezone().isoformat(timespec="milliseconds")
        with self.connect() as connection:
            connection.execute(
                "INSERT INTO audit_events(timestamp,source,kind,message,level,details_json) VALUES(?,?,?,?,?,?)",
                (timestamp, source, kind, message, level, json.dumps(details or {}, sort_keys=True)),
            )
        print(f"[{timestamp[11:23]}] [{source}] [{kind}] {message}", flush=True)

    def snapshot(self, limit: int = 300) -> dict[str, Any]:
        with self.connect() as connection:
            events = [
                {
                    **dict(row),
                    "details": json.loads(row["details_json"]),
                }
                for row in connection.execute(
                    "SELECT * FROM audit_events ORDER BY sequence DESC LIMIT ?", (limit,)
                ).fetchall()
            ]
            grants = [
                {key: value for key, value in dict(row).items() if key != "token"}
                for row in connection.execute(
                    "SELECT * FROM grants ORDER BY rowid DESC LIMIT 50"
                ).fetchall()
            ]
            approvals = [
                dict(row)
                for row in connection.execute(
                    "SELECT * FROM approvals ORDER BY rowid DESC LIMIT 50"
                ).fetchall()
            ]
        for event in events:
            event.pop("details_json", None)
        events.reverse()
        return {"events": events, "grants": grants, "approvals": approvals}
