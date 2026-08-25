From the repository root:
py -3 -m pip install cryptography
The repository is organized as:
laptop_bap_demo/
├── enterprise_demo/    Current production-shaped architecture
├── local_poc/          Preserved original Python proof of concept
├── README.md
├── ARCHITECTURE.md
└── DEMO_SCRIPT.md
Demo 1: Original local Python POC
This is the simpler demonstration for explaining the BAP idea before showing enterprise hardening.
1. Start the POC
Open PowerShell:
cd C:\Users\User\Downloads\Laptop_BAP_CCD\laptop_bap_demo\local_poc
py -3 run_demo.py
The dashboard opens at:
http://127.0.0.1:8765
Keep this window and dashboard open.
2. Run the complete POC smoke test
Open a second PowerShell window:
cd C:\Users\User\Downloads\Laptop_BAP_CCD\laptop_bap_demo\local_poc
py -3 smoke_test.py
Expected ending:
SMOKE TEST PASSED
  [PASS] SessionStart registered a Claude agent run
  [PASS] Unregistered execution without a grant was denied
  [PASS] Fictitious caller-supplied grant was rejected and not forwarded
  [PASS] Development read received and validated a short-lived grant
  [PASS] Development write required approval and then executed
  [PASS] Destructive database operation was denied
  [PASS] Direct database path was rejected
  [PASS] SessionEnd revoked the run's grants
3. Demonstrate the Python AI agent
py -3 python_agent_smoke_test.py
This shows:
Local LLM
  → Python agent
  → laptop connector
  → BAP decision
  → short-lived grant
  → protected database
4. Demonstrate negative cases live
With the dashboard visible:
run-negative-cases.bat
Explain:
- No registered grant: denied.
- Fabricated grant: signature validation fails.
- Direct resource access: target rejects it.
- Denied requests never produce a database-execution event.
5. Stop the POC
stop-demo.bat
Detailed instructions are in [local_poc/README.md](C:/Users/User/Downloads/Laptop_BAP_CCD/laptop_bap_demo/local_poc/README.md).
Demo 2: Enterprise production-shaped BAP
This is the primary leadership demonstration.
Run all commands from:
cd C:\Users\User\Downloads\Laptop_BAP_CCD\laptop_bap_demo
1. Show leadership where policy is configured
Open [policies.cedar](C:/Users/User/Downloads/Laptop_BAP_CCD/laptop_bap_demo/enterprise_demo/enterprise_bap/policies.cedar).
Explain:
These are the enterprise authorization rules. They are not embedded in Claude, ClaudeGuard, the laptop connector, or the model.

Show these policy IDs:
- permit-development-customer-read
- permit-development-write-approval-request
- permit-approved-development-customer-write
- forbid-destructive-database-actions
- forbid-production-from-laptop-agents
Cedar is deny-by-default: no matching permit means deny, and a matching forbid overrides permits. The demo uses the official Cedar evaluator and validates policy against [bap.cedarschema](C:/Users/User/Downloads/Laptop_BAP_CCD/laptop_bap_demo/enterprise_demo/enterprise_bap/bap.cedarschema). Cedar authorization documentation
2. Build everything
powershell -ExecutionPolicy Bypass -File enterprise_demo\orchestration\build_demo.ps1
This:
- Downloads the pinned official Cedar CLI.
- Verifies its SHA-256 checksum.
- Validates Cedar policy.
- Builds claude_guard.exe.
- Builds bap_connector_service.exe.
- Builds bap_resource_client.exe.
- Generates the local demo PKI.
- Creates mTLS certificates.
- Demo-signs the three Windows binaries.
The self-issued signatures may report UnknownError because they are not trusted enterprise certificates. That is expected for this demo.
3. Start the enterprise architecture
enterprise_demo\start-enterprise-demo.bat
Keep this window open.
The dashboard opens at:
http://127.0.0.1:11445
The locally running architecture is:
Claude
  → signed ClaudeGuard
  → Windows named pipe
  → signed laptop connector
  → mTLS BAP front door
  → two Python BAP replicas
  → Cedar policy
  → short-lived signed grant
  → mTLS resource gateway
  → protected resource
Point out:
- There is no HTTP connector on port 11022.
- The connector uses \\.\pipe\Company.BAP.Connector.v1.
- Both BAP replicas share policy/grant/audit state.
- The dashboard is evidence, not enforcement.
4. Run the deterministic enterprise demonstration
Open a second PowerShell window:
cd C:\Users\User\Downloads\Laptop_BAP_CCD\laptop_bap_demo
enterprise_demo\run-enterprise-smoke-test.bat
Expected result:
ENTERPRISE BAP SMOKE TEST PASSED
  [PASS] ClaudeGuard used a signed Windows named-pipe connector; port 11022 was absent
  [PASS] mTLS rejected clients without the connector certificate
  [PASS] Requests were distributed across two BAP replicas with shared state
  [PASS] Read grant executed; write required approval; delete was denied before execution
  [PASS] Missing, fictitious, and direct resource paths were independently denied
  [PASS] Central dashboard captured the full enforcement sequence
What to show on the dashboard
Allowed development read
Follow these events:
1. SESSION_REGISTERED
2. TASK_INTENT_CAPTURED
3. TOOL_INTERCEPTED
4. POLICY_MATCHED
5. GRANT_ISSUED
6. GRANT_VALID
7. RESOURCE_EXECUTED
8. RESOURCE_RESULT_RETURNED
Show that POLICY_MATCHED identifies:
permit-development-customer-read
Explain:
The grant lasts only 60 seconds and is bound to the human, agent run, action, resource, policy version, and gateway audience. Claude never sees the token.

Approval-required write
Explain the two decisions:
1. Cedar initially does not permit the write because humanApproved=false.
2. Cedar permits requesting approval.
3. BAP returns REQUIRE_APPROVAL without issuing an executable grant.
4. After approval, BAP reevaluates the original write.
5. Only permit-approved-development-customer-write can issue the write grant.
Mention that automatic approval activation is a demo shortcut. Production uses an enterprise approval service.
Destructive action denial
Show:
forbid-destructive-database-actions
Then explain:
BAP returns deny, ClaudeGuard translates it into Claude’s PreToolUse permissionDecision: deny, and Claude cancels the command before execution. No grant is issued.

Production resource denial
Show:
forbid-production-from-laptop-agents
Explain:
A developer’s laptop agent cannot access production merely because the developer asked it to. Production is outside the laptop-agent trust zone.

Bypass resistance
Show these events:
- NO_GRANT_DENIED
- GRANT_REJECTED
- DIRECT_PATH_BLOCKED
- DIRECT_ACCESS_DENIED
Explain:
Even if someone disables or bypasses the agent hook, the protected resource remains inaccessible. The gateway requires a valid grant, and the resource accepts only the gateway path. Production network segmentation additionally removes all direct laptop-to-resource routes.

Optional live Claude demonstration
This requires:
- Local LLM on 127.0.0.1:8080
- ccbridge on 127.0.0.1:4080
- Enterprise demo already running
1. Start the bridge
Open another PowerShell window:
cd C:\Users\User\Downloads\Laptop_BAP_CCD\laptop_bap_demo\local_poc
start-ccbridge.bat
2. Start Claude through the local LLM
From the repository root:
enterprise_demo\start-enterprise-local-claude.bat
3. Ask Claude for an allowed read
Run exactly this command and explain the returned BAP evidence: ./enterprise_demo/bap_resource_client/publish/bap_resource_client.exe read customer-123
Expected:
- Cedar allows the request.
- A short-lived grant is issued.
- The gateway validates it.
- The resource returns customer-123.
- Claude explains the non-secret BAP evidence.
4. Ask Claude for a write
Run exactly this command and explain the returned BAP evidence: ./enterprise_demo/bap_resource_client/publish/bap_resource_client.exe write customer-123 status=reviewed
Expected:
- Claude displays an approval prompt.
- Dashboard shows the approval-request policy.
- After approval, Cedar reevaluates the write.
- A separate write grant is issued.
5. Ask Claude for a destructive operation
Run exactly this command: ./enterprise_demo/bap_resource_client/publish/bap_resource_client.exe delete customer-123
Expected:
- ClaudeGuard returns deny.
- Claude does not execute the resource client.
- Dashboard shows forbid-destructive-database-actions.
- No RESOURCE_EXECUTED event appears for the delete.
6. Ask Claude for production access
Run exactly this command: ./enterprise_demo/bap_resource_client/publish/bap_resource_client.exe prod-read customer-123
Expected:
- Cedar returns deny.
- Dashboard shows forbid-production-from-laptop-agents.
- No production grant is issued.
Stop the enterprise demonstration
enterprise_demo\stop-enterprise-demo.bat
Leadership close
Use this:
BAP gives agents zero standing privilege. The model proposes work but never holds credentials or defines policy. Central Cedar policy evaluates the human, device, agent run, action, resource, and current context. A signed laptop service holds a short-lived grant, and the resource gateway independently verifies it. Managed hooks stop denied actions early, while network segmentation and gateway-only resource access provide the unbypassable security boundary. The same BAP platform can support Claude, Cursor, Copilot, MCP, and future agents through thin vendor adapters.

The primary presentation guide is [DEMO_SCRIPT.md](C:/Users/User/Downloads/Laptop_BAP_CCD/laptop_bap_demo/DEMO_SCRIPT.md), and the production design is in [ARCHITECTURE.md](C:/Users/User/Downloads/Laptop_BAP_CCD/laptop_bap_demo/ARCHITECTURE.md).


9:34 PM








ok i ran the local demo, why is step 2 and step 3 not generating events in the dashboard wearas step 4 does. is it expected or a bug?







9:42 PM






Worked for 1m 56s



It was expected behavior in the code, but a bug in my demo instructions.
- smoke_test.py creates private services on random ports with a separate event store.
- python_agent_smoke_test.py does the same, including a temporary fake LLM.
- Their events disappear when each test finishes.
- run-negative-cases.bat calls the live connector on port 8765, so those events appear on your dashboard.
I corrected this and added live-dashboard drivers.
Correct live POC sequence
Window 1 — Start dashboard
cd C:\Users\User\Downloads\Laptop_BAP_CCD\laptop_bap_demo\local_poc
py -3 run_demo.py
Keep http://127.0.0.1:8765 visible.
Window 2 — Positive, approval, and deny cases
cd C:\Users\User\Downloads\Laptop_BAP_CCD\laptop_bap_demo\local_poc
run-live-dashboard-demo.bat
This now generates visible dashboard events for:
- Development read: allow and execute.
- Development write: require approval, then execute.
- Delete: deny without execution.
- Production read: deny without execution.
Show the Python agent lifecycle
run-live-python-agent-demo.bat
This uses a temporary deterministic LLM and writes the full agent lifecycle to the live dashboard. It does not require port 8080.
Show negative grant cases
run-negative-cases.bat
This generates missing-grant and fictitious-grant denial evidence.
Isolated regression tests
These still intentionally do not affect the dashboard:
py -3 smoke_test.py
py -3 python_agent_smoke_test.py
They are CI-style tests, not presentation drivers.
I tested both new live commands successfully, and their events appeared through the live connector. The corrected instructions are in [local_poc/README.md](C:/Users/User/Downloads/Laptop_BAP_CCD/laptop_bap_demo/local_poc/README.md).