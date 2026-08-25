# Laptop Bounded Authority Plane (BAP)

This repository demonstrates zero-standing-privilege access for laptop AI agents. An agent can propose an action, but it never receives an enterprise credential or decides its own authority. A managed adapter registers the run, central BAP evaluates Cedar policy, the connector retains a short-lived bound grant, and a gateway independently validates that grant before the resource executes.

The current production-shaped path uses:

- C#/.NET 8 only for Windows endpoint binaries: `claude_guard.exe`, `bap_connector_service.exe`, and `bap_resource_client.exe`.
- Python for central, portable BAP replicas, front door, resource gateway, dashboard, and protected-resource simulator.
- The official Cedar CLI and a validated Cedar schema/policy set for actual demo decisions.
- Windows named pipes locally, mTLS centrally, RS256 grants, two BAP replicas, correlated append-only audit evidence, and target-side denial of direct access.

## Quick start

Run from PowerShell in this repository:

```powershell
powershell -ExecutionPolicy Bypass -File enterprise_demo\orchestration\build_demo.ps1
enterprise_demo\start-enterprise-demo.bat
```

Keep the dashboard at `http://127.0.0.1:11445` visible. In another terminal:

```powershell
enterprise_demo\run-enterprise-smoke-test.bat
```

Audit state is preserved across starts. Use `py -3 enterprise_demo\orchestration\start_demo.py --reset-state` only when you intentionally want a clean demonstration; the prior database and connector outbox are archived under `enterprise_demo\runtime\archive\`.

Expected evidence includes:

- development read allowed by `permit-development-customer-read`;
- development write requiring approval, then re-evaluated and allowed;
- delete denied by `forbid-destructive-database-actions`;
- production access denied by `forbid-production-from-laptop-agents`;
- missing, fictitious, mismatched, and direct access denied;
- traffic distributed across both BAP replicas;
- no listener on the old lab port 11022.

Stop with:

```powershell
enterprise_demo\stop-enterprise-demo.bat
```

To run Claude Code through the local model, keep the OpenAI-compatible LLM on `127.0.0.1:8080` and `ccbridge` on `127.0.0.1:4080`, start the enterprise demo, then run:

```powershell
enterprise_demo\start-enterprise-local-claude.bat
```

TeaToken authentication is already enforced by the enterprise Claude gateway and is intentionally not reimplemented here. BAP consumes trusted identity context and focuses on authorization of individual agent actions.

## Where policy is configured

Allow/deny logic is not hard-coded in the agent or connector. It is in:

- [Cedar policies](enterprise_demo/enterprise_bap/policies.cedar)
- [Cedar schema](enterprise_demo/enterprise_bap/bap.cedarschema)
- [Demo resource entities](enterprise_demo/enterprise_bap/resources.cedarentities.json)
- [Policy bundle metadata](enterprise_demo/enterprise_bap/policy-bundle.json)

Read [POLICY_MODEL.md](enterprise_demo/POLICY_MODEL.md) for request attributes, example decisions, ownership, deployment, testing, signing, versioning, and rollback.

## Documentation map

- [Enterprise demo README](enterprise_demo/README.md)
- [Architecture](ARCHITECTURE.md)
- [End-to-end demo script](DEMO_SCRIPT.md)
- [Policy and Cedar model](enterprise_demo/POLICY_MODEL.md)
- [Deny and enforcement model](enterprise_demo/ENFORCEMENT_MODEL.md)
- [Claude, Cursor, Copilot, and generic adapters](enterprise_demo/AGENT_ADAPTERS.md)
- [Production deployment blueprint](enterprise_demo/ENTERPRISE_DEPLOYMENT.md)
- [Signing runbook](enterprise_demo/SIGNING_RUNBOOK.md)
- [Audit evidence model, queries, and production storage](enterprise_demo/audit/README.md)

## Repository layout

| Directory | Purpose |
|---|---|
| `enterprise_demo/claude_guard/` | Signed Claude Code hook adapter; Release uses named pipe, Lab build uses port 11022 |
| `enterprise_demo/laptop_connector_service/` | Windows named-pipe and mTLS connector service |
| `enterprise_demo/bap_resource_client/` | Signed demo resource adapter; grants remain in the connector |
| `enterprise_demo/enterprise_bap/` | Python BAP API plus Cedar policy/schema/entities |
| `enterprise_demo/bap_front_door/` | mTLS front door and replica routing |
| `enterprise_demo/resource_gateway/` | Independent grant validation and resource forwarding |
| `enterprise_demo/protected_resource/` | Target-side direct-access denial simulator |
| `enterprise_demo/central_dashboard/` | Central evidence view, not an enforcement service |
| `enterprise_demo/audit/` | Canonical audit schema, production PostgreSQL contract, search and retention design |
| `enterprise_demo/orchestration/` | Build, Cedar installation, start/stop, and smoke test |
| `local_poc/` | Preserved original Python-only proof of concept with independent README/tests |

The preserved Python-only proof is isolated under [local_poc](local_poc/README.md). New production design and stakeholder demonstrations use `enterprise_demo/`.
