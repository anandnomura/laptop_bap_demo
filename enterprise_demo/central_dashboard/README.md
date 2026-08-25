# Central evidence dashboard

Read-only local demonstration UI at `http://127.0.0.1:11445`. Start it with the full demo:

```powershell
enterprise_demo\start-enterprise-demo.bat
```

Then run:

```powershell
enterprise_demo\run-enterprise-smoke-test.bat
```

Use the access-request table to answer who requested what, why, which policy decided it, whether approval occurred, which grant was issued, and whether execution succeeded. Filters cover identity, request/run, action, resource, decision, policy, event type, and time. `Export JSONL` downloads the current evidence filter, and the integrity badge verifies the local append-only hash chain.

API examples and the production event/storage contract are in [../audit/README.md](../audit/README.md). The dashboard is evidence only; stopping or hiding it does not alter enforcement. This localhost UI is intentionally unauthenticated for the demo. Production uses enterprise SSO, role-scoped search, a durable event pipeline, SIEM, and WORM retention.
