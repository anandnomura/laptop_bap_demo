# Stakeholder demo: enterprise BAP end to end

Run every command from the repository root. Allow about 15 minutes and keep the dashboard visible.

## 1. Explain the architecture

Use this sentence:

> The agent proposes an action, but central Cedar policy decides authority. The laptop connector holds a short-lived grant, the resource gateway validates it independently, and network segmentation prevents direct laptop access. The developer and model have no standing resource credential.

Show [policies.cedar](enterprise_demo/enterprise_bap/policies.cedar). Point out that allow/deny rules are configuration, not hard-coded into ClaudeGuard or the connector:

- development read is permitted;
- development write has a separate approval-request permission;
- approved write is a separate permit;
- destructive database operations are forbidden;
- production access from laptop agents is forbidden;
- no matching permit means deny.

## 2. Build

```powershell
powershell -ExecutionPolicy Bypass -File enterprise_demo\orchestration\build_demo.ps1
```

Explain that the build pins and checksum-verifies the official Cedar CLI, builds three .NET Windows binaries, generates demo PKI, and applies demo Authenticode signatures. Production signing is described in `enterprise_demo\SIGNING_RUNBOOK.md`.

## 3. Start

```powershell
enterprise_demo\start-enterprise-demo.bat
```

The dashboard opens at `http://127.0.0.1:11445`. Show the green integrity badge, access-request table, filters, and event sequence. State that this dashboard is evidence, not enforcement, and that production does not use port 11022.

## 4. Run the deterministic demonstration

In a second terminal:

```powershell
enterprise_demo\run-enterprise-smoke-test.bat
```

Expected summary:

```text
ENTERPRISE BAP SMOKE TEST PASSED
  [PASS] ClaudeGuard used a signed Windows named-pipe connector; port 11022 was absent
  [PASS] mTLS rejected clients without the connector certificate
  [PASS] Requests were distributed across two BAP replicas with shared state
  [PASS] Read grant executed; write required approval; delete was denied before execution
  [PASS] Missing, fictitious, and direct resource paths were independently denied
  [PASS] Central dashboard captured the full enforcement sequence
  [PASS] Correlated audit search, secret exclusion, and append-only hash-chain integrity passed
```

## 5. Explain the positive read

On the dashboard, follow:

1. `SESSION_REGISTERED` and `TASK_INTENT_CAPTURED`.
2. `TOOL_INTERCEPTED` with normalized `database.read` / `dev-customer-db`.
3. `POLICY_MATCHED` with `permit-development-customer-read` and policy bundle hash/revision.
4. `GRANT_ISSUED` with a 60-second lifetime.
5. `GRANT_VALID` at the separate resource gateway.
6. `RESOURCE_EXECUTED` and `RESOURCE_RESULT_RETURNED`.

The grant token is not in Claude's command or result; it remains connector-held.

Copy the read request ID from the access table into the Request ID filter. The resulting events share the same request ID while decision, grant, and execution IDs distinguish each stage. Point out the user, managed device, task summary, action/resource, Cedar rule/revision, execution result, and payload hashes. Click `Export JSONL` to show that the same filtered evidence is investigation-ready.

## 6. Explain approval-required write

Show that the initial `databaseWrite` is not permitted. Cedar separately permits `requestDatabaseWriteApproval`, so BAP returns `REQUIRE_APPROVAL` without an executable grant. After mock approval, BAP re-evaluates the original write with `humanApproved=true`; only `permit-approved-development-customer-write` can issue the grant.

State clearly: the demo auto-activates mock approval for flow visibility. Production uses an enterprise approval service and signed approval evidence.

## 7. Explain explicit denies

Show dashboard evidence for:

- `database.delete`: `forbid-destructive-database-actions`;
- production read: `forbid-production-from-laptop-agents`;
- unknown action/resource: `default-deny`.

ClaudeGuard converts BAP deny into Claude's `PreToolUse` `permissionDecision: deny`; Claude cancels the tool before execution. No grant exists.

## 8. Explain bypass resistance

Show these smoke-test events:

- `NO_GRANT_DENIED`: signed resource client with an unknown session;
- `GRANT_REJECTED`: fictitious token fails gateway validation;
- `DIRECT_PATH_BLOCKED`: Claude tries an explicit direct client;
- `DIRECT_ACCESS_DENIED`: a process manually bypasses hooks and contacts the resource.

The last case is crucial: hook bypass still fails because the resource accepts only its gateway path. In production, firewall/VPN/security-group policy also removes the direct route.

Filter `Decision` to `DENY` to show denied proposals separately from executed requests. Then call `Invoke-RestMethod http://127.0.0.1:11445/api/integrity` and show `ok: true`. Explain that production additionally streams evidence to SIEM and WORM storage with signed external checkpoints; the local chain is a demonstrator, not the sole compliance control.

## 9. Optional live Claude + local LLM

Prerequisites:

- OpenAI-compatible local model on `127.0.0.1:8080`;
- the preserved bridge running from `local_poc` on `127.0.0.1:4080`:

```powershell
cd local_poc
start-ccbridge.bat
cd ..
enterprise_demo\start-enterprise-local-claude.bat
```

Prompt Claude:

```text
Run exactly this command and explain the returned BAP evidence: ./enterprise_demo/bap_resource_client/publish/bap_resource_client.exe read customer-123
```

Then request `delete customer-123` to show a Cedar denial before execution.

## 10. Close

Use this summary:

> Cedar is the central source of authorization. Managed agent adapters provide early interception, but the short-lived grant, independent gateway validation, and gateway-only network route provide the durable security boundary. The same connector and policy plane can support Claude, Cursor, Copilot, MCP, or another agent through a thin vendor adapter.

Stop all enterprise-demo processes:

```powershell
enterprise_demo\stop-enterprise-demo.bat
```
