from __future__ import annotations

import html
import json
import os
import secrets
import threading
import time
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from typing import Any
from urllib.parse import urlparse

from demo_common import EventBus, json_request
from mock_db_server import GATEWAY_SECRET, MockDatabaseState


class LaptopConnectorState:
    def __init__(
        self,
        events: EventBus,
        db_state: MockDatabaseState,
        bap_url: str = "http://127.0.0.1:8700",
        db_url: str = "http://127.0.0.1:8800",
    ) -> None:
        self.events = events
        self.db_state = db_state
        self.bap_url = bap_url
        self.db_url = db_url
        self.sessions: dict[str, dict[str, Any]] = {}
        self.authorizations: dict[str, dict[str, Any]] = {}
        self.lock = threading.Lock()
        self.shutdown_event = threading.Event()

    def start_session(self, payload: dict[str, Any]) -> dict[str, Any]:
        session_id = str(payload.get("session_id") or "session-" + secrets.token_hex(4))
        user = str(payload.get("user") or os.environ.get("USERNAME") or os.environ.get("USER") or "developer")
        agent = str(payload.get("agent") or "claude-code")[:80]
        run_prefix = "cc-run" if agent == "claude-code" else "py-run"
        agent_run = run_prefix + "-" + secrets.token_hex(4)
        device = os.environ.get("COMPUTERNAME")
        if not device:
            device = os.uname().nodename if hasattr(os, "uname") else "laptop"
        session = {
            "session_id": session_id,
            "agent_run": agent_run,
            "agent": agent,
            "user": user,
            "device": device,
            "cwd": payload.get("cwd"),
            "task": "Task not captured yet",
            "started_at": int(time.time()),
            "status": "ACTIVE",
            "hook_client": self._client_metadata(payload),
        }
        with self.lock:
            self.sessions[session_id] = session
        self.events.emit(
            "CC HOOK" if agent == "claude-code" else "PY AGENT",
            "SESSION_START",
            f"Registered {agent} session {session_id} as {agent_run}",
            session,
            "success",
        )
        return {"ok": True, "session": session}

    def capture_intent(self, payload: dict[str, Any]) -> dict[str, Any]:
        session_id = str(payload.get("session_id", ""))
        prompt = str(payload.get("prompt") or payload.get("user_prompt") or "")
        with self.lock:
            session = self.sessions.get(session_id)
            if session:
                session["task"] = prompt[:300]
        self.events.emit(
            "CC HOOK" if session and session["agent"] == "claude-code" else "PY AGENT",
            "TASK_INTENT",
            f"Captured delegated task: {prompt[:100]}",
            {"session_id": session_id, "prompt": prompt},
            "info",
        )
        return {"ok": True}

    def authorize_tool(self, payload: dict[str, Any]) -> dict[str, Any]:
        session_id = str(payload.get("session_id", ""))
        tool_name = str(payload.get("tool_name", ""))
        tool_input = payload.get("tool_input") or {}
        with self.lock:
            session = self.sessions.get(session_id)
        if not session:
            self.events.emit(
                "CONNECTOR",
                "FAIL_CLOSED",
                f"Denied {tool_name}: agent session is not registered",
                {"session_id": session_id},
                "error",
            )
            return {"decision": "DENY", "reason": "Agent session is not registered with the laptop BAP connector"}

        classified = self._classify(tool_name, tool_input)
        self.events.emit(
            "PRE-TOOL HOOK" if session["agent"] == "claude-code" else "AGENT ACTION",
            "TOOL_INTERCEPTED",
            f"Intercepted {tool_name}: {classified['summary']}",
            {"session_id": session_id, **classified},
            "info",
        )

        if classified["category"] == "LOCAL":
            return {
                "decision": "ALLOW",
                "reason": "Local workspace action allowed",
                "classification": classified,
            }

        if classified["category"] == "BYPASS":
            self.events.emit(
                "CONNECTOR",
                "BYPASS_BLOCKED",
                "Direct mock database client blocked; use the BAP database client",
                classified,
                "error",
            )
            return {
                "decision": "DENY",
                "reason": "Direct database access is blocked. Use tools/db_client.py through the laptop BAP connector.",
                "classification": classified,
            }

        request = {
            "user": session["user"],
            "agent": session["agent"],
            "agent_run": session["agent_run"],
            "task": session["task"],
            "device": session["device"],
            "action": classified["action"],
            "resource": classified["resource"],
        }
        try:
            status, result = json_request(f"{self.bap_url}/authorize", request, timeout=3)
        except Exception as exc:  # fail closed by design for the demo hook
            self.events.emit(
                "CONNECTOR",
                "BAP_UNAVAILABLE",
                f"BAP is unavailable; tool call denied: {exc}",
                request,
                "error",
            )
            return {"decision": "DENY", "reason": "BAP unavailable; failing closed"}
        if status != 200:
            return {"decision": "DENY", "reason": result.get("error", "BAP authorization failed")}

        authorization = {
            "session_id": session_id,
            "classification": classified,
            "bap": result,
            "created_at": int(time.time()),
            "hook_client": self._client_metadata(payload),
        }
        with self.lock:
            self.authorizations[session_id] = authorization

        decision = str(result.get("decision", "DENY"))
        level = "success" if decision == "ALLOW" else "warning" if decision == "REQUIRE_APPROVAL" else "error"
        self.events.emit(
            "CONNECTOR",
            f"DECISION_{decision}",
            str(result.get("reason", decision)),
            result,
            level,
        )
        return {
            "decision": decision,
            "reason": result.get("reason"),
            "session_id": session_id,
            "classification": classified,
            "grant": result.get("grant"),
            "approval_request_id": result.get("approval_request_id"),
        }

    def record_agent_event(self, payload: dict[str, Any]) -> tuple[int, dict[str, Any]]:
        session_id = str(payload.get("session_id", ""))
        with self.lock:
            session = self.sessions.get(session_id)
        if not session or session.get("agent") == "claude-code":
            return 403, {"ok": False, "error": "Registered Python agent session required"}

        phase = str(payload.get("phase", "")).upper()
        messages = {
            "LLM_REQUEST": "Asked the local LLM to select a bounded action",
            "LLM_PROPOSAL": "Local LLM proposed an action; awaiting BAP authorization",
            "FINAL_RESPONSE": "Local LLM summarized the BAP-controlled result",
            "AGENT_ERROR": "Python agent stopped after an error",
        }
        if phase not in messages:
            return 400, {"ok": False, "error": "Unsupported agent event phase"}
        details = payload.get("details")
        if not isinstance(details, dict):
            details = {}
        self.events.emit(
            "PY AGENT",
            phase,
            messages[phase],
            {"session_id": session_id, **details},
            "error" if phase == "AGENT_ERROR" else "info",
        )
        return 200, {"ok": True}

    def permission_request(self, payload: dict[str, Any]) -> dict[str, Any]:
        session_id = str(payload.get("session_id", ""))
        with self.lock:
            authorization = self.authorizations.get(session_id, {})
        self.events.emit(
            "CC HOOK",
            "USER_APPROVAL_UI",
            "Claude Code displayed a human approval prompt",
            {
                "session_id": session_id,
                "approval_request_id": authorization.get("bap", {}).get("approval_request_id"),
            },
            "warning",
        )
        return {"ok": True}

    def execute_database(self, payload: dict[str, Any]) -> tuple[int, dict[str, Any]]:
        session_id = str(payload.get("session_id", ""))
        operation = str(payload.get("operation", "read"))
        key = str(payload.get("key", "customer-123"))
        value = payload.get("value")
        with self.lock:
            session = self.sessions.get(session_id)
            authorization = self.authorizations.get(session_id)
        if not session or not authorization:
            self.events.emit(
                "DB GATEWAY",
                "NO_GRANT_DENIED",
                f"Denied {operation.upper()} {key}: no registered session with an authorized grant",
                {"session_id": session_id, "operation": operation, "key": key},
                "error",
            )
            return 403, {"ok": False, "error": "No authorized agent session found"}

        classified = authorization["classification"]
        expected_operation = classified["operation"]
        if operation != expected_operation:
            return 403, {"ok": False, "error": "Runtime operation differs from the pre-authorized action"}

        bap_result = authorization["bap"]
        if bap_result.get("decision") == "REQUIRE_APPROVAL":
            request_id = str(bap_result.get("approval_request_id", ""))
            self.events.emit(
                "CONNECTOR",
                "APPROVAL_OBSERVED",
                "Tool executed after Claude's approval prompt; activating the pending demo grant",
                {"session_id": session_id, "approval_request_id": request_id},
                "warning",
            )
            status, approval = json_request(
                f"{self.bap_url}/approve",
                {"request_id": request_id, "approver": session["user"]},
                timeout=3,
            )
            if status != 200 or not approval.get("ok"):
                return 403, {"ok": False, "error": approval.get("reason", "Approval activation failed")}
            bap_result["decision"] = "ALLOW"
            bap_result["grant"] = approval["grant"]

        grant = bap_result.get("grant")
        if not grant:
            return 403, {"ok": False, "error": "BAP did not issue a grant"}

        validation_request = {
            "token": grant["token"],
            "action": classified["action"],
            "resource": classified["resource"],
            "agent_run": session["agent_run"],
        }
        self.events.emit(
            "DB GATEWAY",
            "GRANT_VALIDATE",
            f"Validating {grant['grant_id']} before forwarding the database request",
            validation_request | {"token": "<signed-token>"},
            "info",
        )
        status, validation = json_request(f"{self.bap_url}/validate", validation_request, timeout=3)
        if status != 200 or not validation.get("valid"):
            self.events.emit(
                "DB GATEWAY",
                "GRANT_REJECTED",
                str(validation.get("reason", "Grant validation failed")),
                validation,
                "error",
            )
            return 403, {"ok": False, "error": validation.get("reason", "Grant validation failed")}

        self.events.emit(
            "DB GATEWAY",
            "GRANT_VALID",
            f"Grant {grant['grant_id']} is valid; forwarding to MockDB",
            validation.get("claims", {}),
            "success",
        )
        db_status, db_result = json_request(
            f"{self.db_url}/query",
            {
                "operation": operation,
                "key": key,
                "value": value,
                "agent_run": session["agent_run"],
                "grant_id": grant["grant_id"],
            },
            headers={"X-Demo-Gateway-Secret": GATEWAY_SECRET},
            timeout=3,
        )
        self.events.emit(
            "CONNECTOR",
            "RESULT_RETURNED",
            f"Returned MockDB result to {session['agent']} for {operation.upper()} {key}",
            {"status": db_status, "result": db_result},
            "success" if db_status == 200 else "error",
        )
        return db_status, {
            **db_result,
            "bap_evidence": {
                "agent_run": session["agent_run"],
                "on_behalf_of": session["user"],
                "task": session["task"],
                "grant_id": grant["grant_id"],
                "approved_by": grant["approved_by"],
                "expires_at": grant["exp"],
            },
        }

    def inspect_external_grant(self, payload: dict[str, Any]) -> tuple[int, dict[str, Any]]:
        token = str(payload.get("token", ""))
        action = str(payload.get("action", "database.read"))
        resource = str(payload.get("resource", "dev-customer-db"))
        agent_run = str(payload.get("agent_run", "fictitious-run"))
        self.events.emit(
            "DB GATEWAY",
            "EXTERNAL_GRANT_PRESENTED",
            f"A caller presented an external grant for {action} on {resource}",
            {"token": "<caller-supplied-token>", "action": action, "resource": resource, "agent_run": agent_run},
            "warning",
        )
        status, validation = json_request(
            f"{self.bap_url}/validate",
            {"token": token, "action": action, "resource": resource, "agent_run": agent_run},
            timeout=3,
        )
        if status != 200 or not validation.get("valid"):
            reason = str(validation.get("reason", "Grant validation failed"))
            self.events.emit(
                "DB GATEWAY",
                "FICTITIOUS_GRANT_DENIED",
                f"Rejected caller-supplied grant: {reason}",
                {"action": action, "resource": resource, "agent_run": agent_run, "reason": reason},
                "error",
            )
            return 403, {"ok": False, "error": reason, "forwarded_to_database": False}

        self.events.emit(
            "DB GATEWAY",
            "EXTERNAL_GRANT_DENIED",
            "A valid grant still cannot be injected by a caller; connector-held grants are required",
            {"action": action, "resource": resource, "agent_run": agent_run},
            "error",
        )
        return 403, {
            "ok": False,
            "error": "Externally supplied grants are not accepted",
            "forwarded_to_database": False,
        }

    def post_tool(self, payload: dict[str, Any]) -> dict[str, Any]:
        session_id = str(payload.get("session_id", ""))
        with self.lock:
            session = self.sessions.get(session_id)
        is_claude = bool(session and session.get("agent") == "claude-code")
        self.events.emit(
            "CC HOOK" if is_claude else "PY AGENT",
            "ACTUAL_RESULT",
            f"Recorded completed {payload.get('tool_name', 'tool')} call",
            {
                "session_id": payload.get("session_id"),
                "tool_name": payload.get("tool_name"),
                "tool_use_id": payload.get("tool_use_id"),
                "hook_client": self._client_metadata(payload),
            },
            "success",
        )
        return {"ok": True}

    def end_session(self, payload: dict[str, Any]) -> dict[str, Any]:
        session_id = str(payload.get("session_id", ""))
        with self.lock:
            session = self.sessions.get(session_id)
            if session:
                session["status"] = "CLOSED"
        if session:
            json_request(
                f"{self.bap_url}/revoke-session",
                {"agent_run": session["agent_run"]},
                timeout=3,
            )
            self.events.emit(
                "CC HOOK" if session["agent"] == "claude-code" else "PY AGENT",
                "SESSION_END",
                f"Closed {session['agent_run']} and revoked its grants",
                session,
                "warning",
            )
        return {"ok": True}

    def reset(self) -> None:
        with self.lock:
            self.sessions.clear()
            self.authorizations.clear()
        self.db_state.reset()
        self.events.clear()
        self.events.emit("DEMO", "RESET", "Demo state reset", {}, "warning")

    @staticmethod
    def _classify(tool_name: str, tool_input: dict[str, Any]) -> dict[str, Any]:
        if tool_name == "AgentDatabase":
            operation = str(tool_input.get("operation", "")).lower()
            resource = str(tool_input.get("resource", "dev-customer-db"))
            action_map = {
                "read": "database.read",
                "write": "database.write",
                "delete": "database.delete",
            }
            if operation not in action_map or resource not in {"dev-customer-db", "prod-customer-db"}:
                return {
                    "category": "PROTECTED",
                    "action": "database.unknown",
                    "resource": resource,
                    "operation": operation,
                    "summary": "invalid structured database request",
                }
            return {
                "category": "PROTECTED",
                "action": action_map[operation],
                "resource": resource,
                "operation": operation,
                "summary": f"{action_map[operation]} on {resource}",
            }
        if tool_name not in {"Bash", "PowerShell"}:
            if tool_name.startswith("mcp__"):
                return {
                    "category": "PROTECTED",
                    "action": "mcp.invoke",
                    "resource": tool_name,
                    "operation": "invoke",
                    "summary": f"MCP call {tool_name}",
                }
            return {"category": "LOCAL", "summary": f"Local Claude tool {tool_name}"}

        command = str(tool_input.get("command", ""))
        lowered = command.lower().replace("\\", "/")
        if "direct_db_client.py" in lowered:
            return {"category": "BYPASS", "summary": "attempted direct MockDB access"}
        if "db_client.py" not in lowered:
            return {"category": "LOCAL", "summary": command[:160] or "local shell command"}

        operation = "read"
        for candidate in ("delete", "write", "prod-read", "read"):
            if f" {candidate}" in f" {lowered}":
                operation = candidate
                break
        resource = "prod-customer-db" if operation == "prod-read" else "dev-customer-db"
        action_map = {
            "read": "database.read",
            "prod-read": "database.read",
            "write": "database.write",
            "delete": "database.delete",
        }
        return {
            "category": "PROTECTED",
            "action": action_map[operation],
            "resource": resource,
            "operation": "read" if operation == "prod-read" else operation,
            "summary": f"{action_map[operation]} on {resource}",
        }

    def dashboard_state(self) -> dict[str, Any]:
        with self.lock:
            sessions = json.loads(json.dumps(self.sessions))
            authorizations = json.loads(json.dumps(self.authorizations))
        for authorization in authorizations.values():
            grant = authorization.get("bap", {}).get("grant")
            if grant and "token" in grant:
                grant["token"] = "<signed-token>"
        return {
            "sessions": sessions,
            "authorizations": authorizations,
            "database": self.db_state.snapshot(),
            "events": self.events.snapshot(),
        }

    @staticmethod
    def _client_metadata(payload: dict[str, Any]) -> dict[str, Any]:
        metadata = payload.get("client_metadata")
        if not isinstance(metadata, dict):
            return {}
        allowed = {
            "schema_version",
            "event_id",
            "emitted_at",
            "product",
            "version",
            "build_flavor",
            "hook_action",
            "host",
            "user",
            "process_id",
            "process_architecture",
            "runtime",
            "executable_path",
        }
        return {
            key: value[:500] if isinstance(value, str) else value
            for key, value in metadata.items()
            if key in allowed and isinstance(value, (str, int, float, bool))
        }


def _dashboard_html() -> bytes:
    page = r"""
<!doctype html>
<html lang="en">
<head>
  <meta charset="utf-8">
  <meta name="viewport" content="width=device-width, initial-scale=1">
  <title>Laptop BAP Agent Runtime Demo</title>
  <style>
    :root { color-scheme: dark; --bg:#08111f; --panel:#101d31; --border:#263a56; --text:#ecf4ff; --muted:#9fb2ca; --blue:#48a8ff; --green:#49d17d; --amber:#f5b942; --red:#ff6577; }
    * { box-sizing:border-box; }
    body { margin:0; background:var(--bg); color:var(--text); font:14px/1.45 system-ui,Segoe UI,sans-serif; }
    header { padding:20px 24px 14px; border-bottom:1px solid var(--border); }
    h1 { margin:0 0 4px; font-size:22px; font-weight:600; }
    .subtitle { color:var(--muted); }
    main { padding:18px 24px 32px; display:grid; gap:16px; }
    .flow { display:grid; grid-template-columns:repeat(5,minmax(120px,1fr)); gap:8px; align-items:center; }
    .node { min-height:78px; padding:12px; background:var(--panel); border:1px solid var(--border); border-radius:10px; text-align:center; display:grid; place-content:center; }
    .node strong { display:block; color:var(--blue); }
    .arrow { display:none; }
    .grid { display:grid; grid-template-columns:2fr 1fr; gap:16px; align-items:start; }
    .panel { background:var(--panel); border:1px solid var(--border); border-radius:10px; overflow:hidden; }
    .panel h2 { margin:0; padding:11px 14px; font-size:14px; border-bottom:1px solid var(--border); }
    #events { max-height:540px; overflow:auto; }
    .event { display:grid; grid-template-columns:78px 116px 150px 1fr; gap:10px; padding:9px 12px; border-bottom:1px solid rgba(38,58,86,.55); }
    .event .time,.event .source { color:var(--muted); }
    .event.success .kind { color:var(--green); }
    .event.warning .kind { color:var(--amber); }
    .event.error .kind { color:var(--red); }
    pre { margin:0; padding:12px; white-space:pre-wrap; word-break:break-word; color:#d7e6fa; }
    .empty { padding:18px; color:var(--muted); }
    @media (max-width:850px) { .flow { grid-template-columns:1fr; } .grid { grid-template-columns:1fr; } .event { grid-template-columns:68px 95px 1fr; } .event .message { grid-column:1/-1; } }
  </style>
</head>
<body>
  <header>
    <h1>Laptop BAP Runtime — Live Execution Evidence</h1>
    <div class="subtitle">Agent proposes → Connector intercepts → BAP authorizes → Gateway validates → Database executes</div>
  </header>
  <main>
    <section class="flow" aria-label="Runtime sequence">
      <div class="node"><strong>1. AI Agent</strong><span>Claude or local Python agent</span></div>
      <div class="node"><strong>2. Interceptor</strong><span>Hook or agent action API</span></div>
      <div class="node"><strong>3. Laptop Connector</strong><span>Session and grant context</span></div>
      <div class="node"><strong>4. BAP + Gateway</strong><span>Policy and validation</span></div>
      <div class="node"><strong>5. MockDB</strong><span>Protected execution</span></div>
    </section>
    <section class="grid">
      <div class="panel"><h2>Live sequence</h2><div id="events"><div class="empty">Waiting for agent events…</div></div></div>
      <div style="display:grid;gap:16px">
        <div class="panel"><h2>Latest agent session</h2><pre id="session">None</pre></div>
        <div class="panel"><h2>Latest BAP decision</h2><pre id="authorization">None</pre></div>
        <div class="panel"><h2>Mock database state</h2><pre id="database">Loading…</pre></div>
      </div>
    </section>
  </main>
  <script>
    const eventsEl = document.getElementById('events');
    const sessionEl = document.getElementById('session');
    const authorizationEl = document.getElementById('authorization');
    const dbEl = document.getElementById('database');
    let lastSequence = 0;
    function escapeHtml(value) { const e=document.createElement('div'); e.textContent=value; return e.innerHTML; }
    async function refresh() {
      try {
        const response = await fetch('/api/state', {cache:'no-store'});
        const state = await response.json();
        const events = state.events || [];
        eventsEl.innerHTML = events.length ? events.map(event => `
          <div class="event ${escapeHtml(event.level)}">
            <span class="time">${escapeHtml(event.timestamp.slice(11,19))}</span>
            <span class="source">${escapeHtml(event.source)}</span>
            <span class="kind">${escapeHtml(event.kind)}</span>
            <span class="message">${escapeHtml(event.message)}</span>
          </div>`).join('') : '<div class="empty">Waiting for agent events…</div>';
        const sessions = Object.values(state.sessions || {});
        const authorizations = Object.values(state.authorizations || {});
        sessionEl.textContent = sessions.length ? JSON.stringify(sessions[sessions.length-1], null, 2) : 'None';
        authorizationEl.textContent = authorizations.length ? JSON.stringify(authorizations[authorizations.length-1].bap, null, 2) : 'None';
        dbEl.textContent = JSON.stringify(state.database || {}, null, 2);
        const newest = events.length ? events[events.length-1].sequence : 0;
        if (newest !== lastSequence) { eventsEl.scrollTop = eventsEl.scrollHeight; lastSequence = newest; }
      } catch (error) {
        eventsEl.innerHTML = '<div class="empty">Dashboard cannot reach the connector.</div>';
      }
    }
    refresh();
    setInterval(refresh, 800);
  </script>
</body>
</html>
"""
    return page.encode("utf-8")


def build_connector_server(host: str, port: int, state: LaptopConnectorState) -> ThreadingHTTPServer:
    dashboard = _dashboard_html()

    class Handler(BaseHTTPRequestHandler):
        def log_message(self, _format: str, *_args: object) -> None:
            return

        def _read(self) -> dict[str, Any]:
            length = int(self.headers.get("Content-Length", "0"))
            return json.loads(self.rfile.read(length) or b"{}")

        def _send_json(self, status: int, value: dict[str, Any]) -> None:
            body = json.dumps(value).encode("utf-8")
            self.send_response(status)
            self.send_header("Content-Type", "application/json")
            self.send_header("Cache-Control", "no-store")
            self.send_header("Content-Length", str(len(body)))
            self.end_headers()
            self.wfile.write(body)

        def do_GET(self) -> None:
            path = urlparse(self.path).path
            if path == "/":
                self.send_response(200)
                self.send_header("Content-Type", "text/html; charset=utf-8")
                self.send_header("Content-Length", str(len(dashboard)))
                self.end_headers()
                self.wfile.write(dashboard)
            elif path == "/health":
                self._send_json(200, {"ok": True, "service": "laptop-connector"})
            elif path == "/api/state":
                self._send_json(200, state.dashboard_state())
            else:
                self._send_json(404, {"error": "not found"})

        def do_POST(self) -> None:
            path = urlparse(self.path).path
            payload = self._read()
            if path == "/session/start":
                self._send_json(200, state.start_session(payload))
            elif path == "/intent":
                self._send_json(200, state.capture_intent(payload))
            elif path == "/hook/pre-tool":
                self._send_json(200, state.authorize_tool(payload))
            elif path == "/hook/permission":
                self._send_json(200, state.permission_request(payload))
            elif path == "/hook/post-tool":
                self._send_json(200, state.post_tool(payload))
            elif path == "/agent/event":
                status, result = state.record_agent_event(payload)
                self._send_json(status, result)
            elif path == "/agent/authorize":
                self._send_json(200, state.authorize_tool(payload))
            elif path == "/agent/action/result":
                self._send_json(200, state.post_tool(payload))
            elif path == "/session/end":
                self._send_json(200, state.end_session(payload))
            elif path == "/db/execute":
                status, result = state.execute_database(payload)
                self._send_json(status, result)
            elif path == "/demo/external-grant-attempt":
                status, result = state.inspect_external_grant(payload)
                self._send_json(status, result)
            elif path == "/reset":
                state.reset()
                self._send_json(200, {"ok": True})
            elif path == "/shutdown":
                state.shutdown_event.set()
                self._send_json(200, {"ok": True})
            else:
                self._send_json(404, {"error": "not found"})

    return ThreadingHTTPServer((host, port), Handler)
