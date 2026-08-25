from __future__ import annotations

import argparse
import json
import sys
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from urllib.parse import urlparse


DEMO_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(DEMO_ROOT))

from common.audit_store import AuditStore  # noqa: E402
from common.paths import DASHBOARD_PORT, STATE_DB, ensure_runtime  # noqa: E402


PAGE = r"""<!doctype html>
<html lang="en"><head><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1">
<title>Enterprise BAP — Central Evidence</title>
<style>
:root{color-scheme:dark;--bg:#07101d;--panel:#101d30;--line:#293d59;--text:#edf5ff;--muted:#9cb1ca;--blue:#56aaff;--green:#4ed181;--amber:#f1b94b;--red:#ff6c7b}
*{box-sizing:border-box}body{margin:0;background:var(--bg);color:var(--text);font:14px/1.45 Segoe UI,system-ui,sans-serif}header{padding:18px 24px;border-bottom:1px solid var(--line)}h1{margin:0;font-size:22px}.sub{color:var(--muted)}main{padding:18px 24px;display:grid;gap:16px}.flow{display:grid;grid-template-columns:repeat(6,1fr);gap:8px}.node,.panel{background:var(--panel);border:1px solid var(--line);border-radius:10px}.node{padding:11px;text-align:center}.node b{display:block;color:var(--blue)}.grid{display:grid;grid-template-columns:2fr 1fr;gap:16px}.panel h2{font-size:14px;margin:0;padding:10px 12px;border-bottom:1px solid var(--line)}#events{max-height:600px;overflow:auto}.event{display:grid;grid-template-columns:95px 145px 180px 1fr;gap:8px;padding:8px 11px;border-bottom:1px solid #22344d}.time,.source{color:var(--muted)}.success .kind{color:var(--green)}.warning .kind{color:var(--amber)}.error .kind{color:var(--red)}pre{margin:0;padding:12px;white-space:pre-wrap;word-break:break-word}.notice{color:var(--amber)}@media(max-width:900px){.flow{grid-template-columns:1fr 1fr}.grid{grid-template-columns:1fr}.event{grid-template-columns:80px 120px 1fr}.message{grid-column:1/-1}}
</style></head><body><header><h1>Enterprise BAP — Central Execution Evidence</h1><div class="sub">Local enterprise-shaped simulation. Dashboard is a demo/support surface, not the laptop connector interface.</div></header>
<main><section class="flow"><div class="node"><b>Claude</b>Managed hooks</div><div class="node"><b>ClaudeGuard</b>Signed adapter</div><div class="node"><b>Connector</b>Named pipe service</div><div class="node"><b>BAP Front Door</b>mTLS + load balance</div><div class="node"><b>BAP Replicas</b>Shared policy state</div><div class="node"><b>Gateway</b>Grant-enforced resource</div></section>
<section class="grid"><div class="panel"><h2>Central audit sequence</h2><div id="events"></div></div><div style="display:grid;gap:16px"><div class="panel"><h2>Short-lived grants</h2><pre id="grants">Loading…</pre></div><div class="panel"><h2>Approval state</h2><pre id="approvals">Loading…</pre></div><div class="panel"><h2>Security note</h2><pre class="notice">Production access requires enterprise authentication. Local dashboard mode is explicitly enabled only for this demo.</pre></div></div></section></main>
<script>const e=document.querySelector('#events'),g=document.querySelector('#grants'),a=document.querySelector('#approvals');let last=0;const esc=v=>{const d=document.createElement('div');d.textContent=v;return d.innerHTML};async function refresh(){try{const r=await fetch('/api/state',{cache:'no-store'}),s=await r.json();e.innerHTML=(s.events||[]).map(x=>`<div class="event ${esc(x.level)}"><span class="time">${esc(x.timestamp.slice(11,23))}</span><span class="source">${esc(x.source)}</span><span class="kind">${esc(x.kind)}</span><span class="message">${esc(x.message)}</span></div>`).join('')||'<pre>Waiting for evidence…</pre>';g.textContent=JSON.stringify(s.grants||[],null,2);a.textContent=JSON.stringify(s.approvals||[],null,2);const n=s.events?.at(-1)?.sequence||0;if(n!==last){e.scrollTop=e.scrollHeight;last=n}}catch{e.innerHTML='<pre>Dashboard cannot read shared audit state.</pre>'}}refresh();setInterval(refresh,700)</script></body></html>""".encode()


def build_server(port: int, store: AuditStore) -> ThreadingHTTPServer:
    class Handler(BaseHTTPRequestHandler):
        def log_message(self, _format: str, *_args: object) -> None:
            return

        def do_GET(self) -> None:
            path = urlparse(self.path).path
            if path == "/":
                body = PAGE
                content_type = "text/html; charset=utf-8"
            elif path == "/api/state":
                body = json.dumps(store.snapshot()).encode()
                content_type = "application/json"
            elif path == "/health":
                body = json.dumps({"ok": True, "service": "central-dashboard"}).encode()
                content_type = "application/json"
            else:
                self.send_response(404)
                self.end_headers()
                return
            self.send_response(200)
            self.send_header("Content-Type", content_type)
            self.send_header("Cache-Control", "no-store")
            self.send_header("Content-Length", str(len(body)))
            self.end_headers()
            self.wfile.write(body)

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
