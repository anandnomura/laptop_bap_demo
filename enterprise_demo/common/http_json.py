from __future__ import annotations

import json
import urllib.error
import urllib.request
from typing import Any


def request_json(
    url: str,
    payload: dict[str, Any] | None = None,
    *,
    method: str = "POST",
    headers: dict[str, str] | None = None,
    timeout: float = 5,
    ssl_context: Any = None,
) -> tuple[int, dict[str, Any]]:
    data = None if payload is None else json.dumps(payload).encode("utf-8")
    request_headers = {"Content-Type": "application/json", **(headers or {})}
    request = urllib.request.Request(url, data=data, method=method, headers=request_headers)
    try:
        with urllib.request.urlopen(request, timeout=timeout, context=ssl_context) as response:
            body = response.read().decode("utf-8")
            return response.status, json.loads(body) if body else {}
    except urllib.error.HTTPError as error:
        body = error.read().decode("utf-8")
        try:
            parsed = json.loads(body) if body else {}
        except json.JSONDecodeError:
            parsed = {"error": body or str(error)}
        return error.code, parsed
