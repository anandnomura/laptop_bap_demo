# Production-shaped enterprise BAP demo

This demo runs the complete laptop-to-enterprise path locally while preserving the intended production trust boundaries:

```text
Claude Code
  -> managed PreToolUse hook / signed claude_guard.exe
  -> authenticated Windows named pipe
  -> signed laptop connector service
  -> mTLS BAP front door
  -> two Python BAP replicas using Cedar policy
  -> short-lived signed grant
  -> mTLS resource gateway
  -> protected resource
```

The central dashboard at `http://127.0.0.1:11445` displays evidence; it is not an enforcement endpoint. Port 11022 is unused.

## Build and run

From the repository root:

```powershell
powershell -ExecutionPolicy Bypass -File enterprise_demo\orchestration\build_demo.ps1
enterprise_demo\start-enterprise-demo.bat
```

In another terminal:

```powershell
enterprise_demo\run-enterprise-smoke-test.bat
```

Stop everything with:

```powershell
enterprise_demo\stop-enterprise-demo.bat
```

The build downloads the pinned official Cedar CLI, verifies its checksum, builds the three Windows binaries, creates demo PKI, and applies a demo Authenticode signature. Generated tools, keys, certificates, binaries, logs, databases, and runtime state are ignored by Git.

## Directory guide

Every active component has its own README with exact verification commands:

| Directory | Role | Run/test instructions |
|---|---|---|
| `claude_guard/` | Claude Code Windows hook adapter | [README](claude_guard/README.md) |
| `laptop_connector_service/` | Windows named-pipe/mTLS service | [README](laptop_connector_service/README.md) |
| `bap_resource_client/` | Signed resource adapter and negative client | [README](bap_resource_client/README.md) |
| `enterprise_bap/` | Python BAP API and Cedar policy | [README](enterprise_bap/README.md) |
| `bap_front_door/` | mTLS ingress and replica routing | [README](bap_front_door/README.md) |
| `resource_gateway/` | Independent grant enforcement | [README](resource_gateway/README.md) |
| `protected_resource/` | Gateway-only target simulator | [README](protected_resource/README.md) |
| `central_dashboard/` | Read-only evidence UI | [README](central_dashboard/README.md) |
| `demo_pki/` | Demo certificates and signing | [README](demo_pki/README.md) |
| `common/` | Shared Python library | [README](common/README.md) |
| `orchestration/` | Build/start/stop/smoke test | [README](orchestration/README.md) |

`runtime/` is generated and Git-ignored. Do not add source or policy files there.

## Read these first

- [POLICY_MODEL.md](POLICY_MODEL.md): exactly where allow/deny/approval decisions come from and how production policy is governed.
- [ENFORCEMENT_MODEL.md](ENFORCEMENT_MODEL.md): how a deny stops Claude and why the gateway remains the final boundary.
- [AGENT_ADAPTERS.md](AGENT_ADAPTERS.md): Claude, Cursor, Copilot, MCP, and generic-agent adaptation.
- [ENTERPRISE_DEPLOYMENT.md](ENTERPRISE_DEPLOYMENT.md): endpoint, central services, network segmentation, scaling, and rollout.
- [SIGNING_RUNBOOK.md](SIGNING_RUNBOOK.md): production binary signing and trust policy.
- [../DEMO_SCRIPT.md](../DEMO_SCRIPT.md): presentation-ready end-to-end script.

## Demo versus production

The demo uses Python HTTP services on localhost, SQLite, a downloaded Cedar CLI process, demo PKI, self-issued Authenticode certificates, and automatic mock approval activation. Production uses container orchestration, durable shared stores, a central Cedar runtime, enterprise PKI/HSM, an actual approval service, explicit Windows service/pipe ACLs, full signature validation, and network-enforced gateway-only resource paths.
