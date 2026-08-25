from __future__ import annotations

import argparse
import json
import sys
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from urllib.parse import parse_qs, urlparse

DEMO_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(DEMO_ROOT))

from common.audit_store import AuditStore  # noqa: E402
from common.paths import DASHBOARD_PORT, STATE_DB, ensure_runtime  # noqa: E402

PAGE = r"""<!doctype html>
<html lang="en"><head><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1"><title>Enterprise BAP - Central Evidence</title>
<style>
:root{color-scheme:dark;--bg:#07101d;--panel:#101d30;--line:#293d59;--text:#edf5ff;--muted:#9cb1ca;--blue:#56aaff;--green:#4ed181;--amber:#f1b94b;--red:#ff6c7b}*{box-sizing:border-box}body{margin:0;background:var(--bg);color:var(--text);font:14px/1.4 Segoe UI,system-ui,sans-serif}header{padding:18px 24px;border-bottom:1px solid var(--line);display:flex;justify-content:space-between;gap:12px}h1{margin:0;font-size:22px}.sub,.muted{color:var(--muted)}main{padding:18px 24px;display:grid;gap:16px}.flow,.filters{display:grid;grid-template-columns:repeat(6,1fr);gap:8px}.node,.panel{background:var(--panel);border:1px solid var(--line);border-radius:10px}.node{padding:11px;text-align:center}.node b{display:block;color:var(--blue)}.panel h2{font-size:14px;margin:0;padding:10px 12px;border-bottom:1px solid var(--line)}.filters{padding:12px}.filters input,.filters select,.filters button,.filters a{min-width:0;background:#081425;color:var(--text);border:1px solid var(--line);border-radius:6px;padding:8px;text-decoration:none}.filters button{cursor:pointer;background:#163459}.table-wrap{overflow:auto;max-height:380px}table{width:100%;border-collapse:collapse;white-space:nowrap}th,td{text-align:left;padding:7px 9px;border-bottom:1px solid #22344d;max-width:280px;overflow:hidden;text-overflow:ellipsis}th{position:sticky;top:0;background:#16243a;color:var(--muted)}#events{max-height:440px;overflow:auto}.event{display:grid;grid-template-columns:95px 145px 180px 1fr;gap:8px;padding:8px 11px;border-bottom:1px solid #22344d}.time,.source{color:var(--muted)}.success .kind,.ok{color:var(--green)}.warning .kind,.warn{color:var(--amber)}.error .kind,.bad{color:var(--red)}.integrity{border:1px solid var(--line);border-radius:20px;padding:6px 12px;height:max-content}pre{margin:0;padding:12px;white-space:pre-wrap;word-break:break-word}@media(max-width:1000px){.flow,.filters{grid-template-columns:1fr 1fr}.event{grid-template-columns:80px 120px 1fr}.message{grid-column:1/-1}}
</style></head><body><header><div><h1>Enterprise BAP - Central Execution Evidence</h1><div class="sub">Searchable, correlated evidence from hook intent through resource execution.</div></div><div id="integrity" class="integrity">Checking integrity...</div></header>
<main><section class="flow"><div class="node"><b>Claude</b>Managed hooks</div><div class="node"><b>ClaudeGuard</b>Signed adapter</div><div class="node"><b>Connector</b>Named pipe service</div><div class="node"><b>BAP Front Door</b>mTLS + load balance</div><div class="node"><b>BAP Replicas</b>Cedar decisions</div><div class="node"><b>Gateway</b>Grant execution</div></section>
<section class="panel"><h2>Audit search and export</h2><form id="filters" class="filters"><input name="user_id" placeholder="User"><input name="request_id" placeholder="Request ID"><input name="agent_run_id" placeholder="Agent run"><input name="action" placeholder="Action"><input name="resource" placeholder="Resource"><select name="decision"><option value="">Any decision</option><option>ALLOW</option><option>REQUIRE_APPROVAL</option><option>DENY</option></select><input name="policy_rule_id" placeholder="Policy rule"><input name="kind" placeholder="Event kind"><input name="from" placeholder="From UTC (ISO 8601)"><input name="to" placeholder="To UTC (ISO 8601)"><button type="submit">Search</button><a id="export" href="/api/export">Export JSONL</a></form></section>
<section class="panel"><h2>Access request timelines - who, why, decision, and execution</h2><div class="table-wrap"><table><thead><tr><th>UTC time</th><th>User</th><th>Task</th><th>Action / resource</th><th>Decision</th><th>Policy</th><th>Approval</th><th>Grant</th><th>Execution</th><th>Request</th></tr></thead><tbody id="access"></tbody></table></div></section>
<section class="panel"><h2>Immutable event sequence</h2><div id="events"></div></section><section class="panel"><h2>Active demo state (secrets excluded)</h2><pre id="state"></pre></section></main>
<script>
const esc=v=>{const d=document.createElement('div');d.textContent=v??'';return d.innerHTML},form=document.querySelector('#filters'),events=document.querySelector('#events'),access=document.querySelector('#access'),integrity=document.querySelector('#integrity'),state=document.querySelector('#state'),exp=document.querySelector('#export');const query=()=>new URLSearchParams(new FormData(form));
async function refresh(){try{const q=query(),[er,ar,sr,ir]=await Promise.all([fetch('/api/audit?'+q),fetch('/api/access?'+q),fetch('/api/state'),fetch('/api/integrity')]),es=await er.json(),as=await ar.json(),ss=await sr.json(),iv=await ir.json();events.innerHTML=(es.events||[]).map(x=>`<div class="event ${esc(x.level)}"><span class="time">${esc(x.timestamp?.slice(0,23))}</span><span class="source">${esc(x.source)}</span><span class="kind">${esc(x.kind)}</span><span class="message">${esc(x.message)} <span class="muted">${esc(x.request_id||'')}</span></span></div>`).join('')||'<pre>No matching evidence.</pre>';access.innerHTML=(as.access||[]).map(x=>`<tr title="Trace: ${esc(x.trace_id)}"><td>${esc(x.requested_at_utc)}</td><td>${esc(x.user_id)}</td><td>${esc(x.task_summary)}</td><td>${esc(x.action)} / ${esc(x.resource)} ${esc(x.resource_key||'')}</td><td>${esc(x.decision)}<br><span class="muted">${esc(x.decision_reason)}</span></td><td>${esc(x.policy_rule_id)} @ ${esc(x.policy_revision)}</td><td>${esc(x.approver_id||x.approval_request_id||'-')}</td><td>${esc(x.grant_id||'-')}</td><td>${esc(x.execution_outcome)} ${esc(x.execution_id||'')}</td><td>${esc(x.request_id)}</td></tr>`).join('')||'<tr><td colspan="10">No matching access requests.</td></tr>';integrity.className='integrity '+(iv.ok?'ok':'bad');integrity.textContent=iv.ok?`Chain verified: ${iv.checked} events`:`INTEGRITY FAILURE at ${iv.sequence}`;state.textContent=JSON.stringify({grants:ss.grants,approvals:ss.approvals},null,2);exp.href='/api/export?'+q;}catch(error){events.innerHTML='<pre class="bad">Dashboard query failed: '+esc(error)+'</pre>'}}
form.addEventListener('submit',e=>{e.preventDefault();refresh()});refresh();setInterval(refresh,2000);
</script></body></html>""".encode()


def query_filters(query: dict[str, list[str]]) -> tuple[dict[str, str], int, int]:
    filters = {key: values[0] for key, values in query.items() if key not in {"limit", "offset"} and values and values[0]}
    try:
        limit = max(1, min(int(query.get("limit", ["300"])[0]), 1000))
        offset = max(0, int(query.get("offset", ["0"])[0]))
    except ValueError:
        limit, offset = 300, 0
    return filters, limit, offset


def build_server(port: int, store: AuditStore) -> ThreadingHTTPServer:
    class Handler(BaseHTTPRequestHandler):
        def log_message(self, _format: str, *_args: object) -> None:
            return

        def respond(self, status: int, body: bytes, content_type: str, disposition: str | None = None) -> None:
            self.send_response(status)
            self.send_header("Content-Type", content_type)
            self.send_header("Cache-Control", "no-store")
            if disposition:
                self.send_header("Content-Disposition", disposition)
            self.send_header("Content-Length", str(len(body)))
            self.end_headers()
            self.wfile.write(body)

        def do_GET(self) -> None:
            parsed = urlparse(self.path)
            filters, limit, offset = query_filters(parse_qs(parsed.query))
            if parsed.path == "/":
                self.respond(200, PAGE, "text/html; charset=utf-8")
            elif parsed.path == "/api/state":
                self.respond(200, json.dumps(store.snapshot()).encode(), "application/json")
            elif parsed.path == "/api/audit":
                self.respond(200, json.dumps({"events": store.search_events(filters, limit, offset)}).encode(), "application/json")
            elif parsed.path == "/api/access":
                self.respond(200, json.dumps({"access": store.search_access(filters, limit)}).encode(), "application/json")
            elif parsed.path == "/api/integrity":
                self.respond(200, json.dumps(store.verify_chain()).encode(), "application/json")
            elif parsed.path == "/api/export":
                rows = store.search_events(filters, limit=1000, offset=offset)
                body = ("\n".join(json.dumps(row, sort_keys=True) for row in rows) + "\n").encode()
                self.respond(200, body, "application/x-ndjson", 'attachment; filename="bap-audit-export.jsonl"')
            elif parsed.path == "/health":
                self.respond(200, b'{"ok":true,"service":"central-dashboard"}', "application/json")
            else:
                self.respond(404, b'{"ok":false,"error":"Not found"}', "application/json")

    return ThreadingHTTPServer(("127.0.0.1", port), Handler)


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--port", type=int, default=DASHBOARD_PORT)
    arguments = parser.parse_args()
    ensure_runtime()
    store = AuditStore(STATE_DB)
    store.emit("CENTRAL DASHBOARD", "SERVICE_READY", f"Demo dashboard listening on 127.0.0.1:{arguments.port}")
    build_server(arguments.port, store).serve_forever()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
