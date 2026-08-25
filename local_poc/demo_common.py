from __future__ import annotations

import json
import threading
import time
import urllib.error
import urllib.request
from dataclasses import asdict, dataclass
from datetime import datetime, timezone
from typing import Any


@dataclass
class DemoEvent:
    sequence: int
    timestamp: str
    source: str
    kind: str
    message: str
    details: dict[str, Any]
    level: str = "info"


class EventBus:
    def __init__(self, max_events: int = 500) -> None:
        self._events: list[DemoEvent] = []
        self._max_events = max_events
        self._sequence = 0
        self._lock = threading.Lock()

    def emit(
        self,
        source: str,
        kind: str,
        message: str,
        details: dict[str, Any] | None = None,
        level: str = "info",
    ) -> DemoEvent:
        with self._lock:
            self._sequence += 1
            event = DemoEvent(
                sequence=self._sequence,
                timestamp=datetime.now(timezone.utc).astimezone().isoformat(timespec="seconds"),
                source=source,
                kind=kind,
                message=message,
                details=details or {},
                level=level,
            )
            self._events.append(event)
            self._events = self._events[-self._max_events :]

        colors = {
            "info": "\033[36m",
            "success": "\033[32m",
            "warning": "\033[33m",
            "error": "\033[31m",
        }
        color = colors.get(level, "")
        reset = "\033[0m"
        print(
            f"{color}[{event.timestamp[11:19]}] "
            f"[{source:<12}] [{kind:<16}] {message}{reset}",
            flush=True,
        )
        return event

    def snapshot(self) -> list[dict[str, Any]]:
        with self._lock:
            return [asdict(item) for item in self._events]

    def clear(self) -> None:
        with self._lock:
            self._events.clear()
            self._sequence = 0


def json_request(
    url: str,
    payload: dict[str, Any] | None = None,
    method: str = "POST",
    headers: dict[str, str] | None = None,
    timeout: float = 5.0,
) -> tuple[int, dict[str, Any]]:
    data = None if payload is None else json.dumps(payload).encode("utf-8")
    request_headers = {"Content-Type": "application/json"}
    request_headers.update(headers or {})
    request = urllib.request.Request(
        url,
        data=data,
        headers=request_headers,
        method=method,
    )
    try:
        with urllib.request.urlopen(request, timeout=timeout) as response:
            body = response.read().decode("utf-8")
            return response.status, json.loads(body) if body else {}
    except urllib.error.HTTPError as exc:
        body = exc.read().decode("utf-8")
        try:
            parsed = json.loads(body) if body else {}
        except json.JSONDecodeError:
            parsed = {"error": body or str(exc)}
        return exc.code, parsed


def wait_for_url(url: str, seconds: float = 15.0) -> bool:
    deadline = time.time() + seconds
    while time.time() < deadline:
        try:
            status, _ = json_request(url, method="GET", timeout=0.5)
            if status == 200:
                return True
        except (OSError, urllib.error.URLError, TimeoutError):
            pass
        time.sleep(0.2)
    return False

