# ClaudeGuard

Signed C#/.NET 8 Windows adapter for Claude Code hooks. It reads hook JSON from standard input and returns Claude's decision JSON on standard output. Its Release build communicates only through `\\.\pipe\Company.BAP.Connector.v1`; it does not open or call TCP port 11022.

## Build Release

From the repository root, use the complete build so connector, PKI, signatures, and Cedar are consistent:

```powershell
powershell -ExecutionPolicy Bypass -File enterprise_demo\orchestration\build_demo.ps1
```

Output:

```text
enterprise_demo\claude_guard\publish\claude_guard.exe
```

## Health test

Start the full enterprise demo, then:

```powershell
enterprise_demo\claude_guard\publish\claude_guard.exe --health
```

Expected: the signed connector is reachable through `Company.BAP.Connector.v1`.

## Full smoke test

```powershell
enterprise_demo\start-enterprise-demo.bat
enterprise_demo\run-enterprise-smoke-test.bat
```

This proves allow, ask, deny, fail-closed behavior, command binding, signed named-pipe callers, and resource enforcement.

## Stakeholder demo

Use the repository [DEMO_SCRIPT.md](../../DEMO_SCRIPT.md). ClaudeGuard evidence appears as `SESSION_REGISTERED`, `TASK_INTENT_CAPTURED`, `TOOL_INTERCEPTED`, and the final hook decision. A Cedar deny causes ClaudeGuard to return `permissionDecision: deny`, so Claude does not execute the command.

## Lab build

`build-lab.bat` creates `publish-lab\claude_guard_lab.exe`, which can use the test connector on localhost port 11022 and includes explicit debug/lab-bypass switches. It is for an administrator-controlled personal lab only. Never sign, allowlist, package, or deploy the Lab binary to controlled laptops.

Release has no runtime bypass flags. Emergency disablement is a centrally managed, administrator-controlled policy action with an audit record.

## Production installation

Install Release under `C:\Program Files\Company\BAP\claude_guard.exe`, sign with the corporate publisher, allow it through WDAC/App Control, and reference it only from enterprise-managed Claude settings. Developers must not control the executable, settings, connector service, named-pipe ACL, or signer trust.

Claude Code starts the executable directly and supplies event JSON on stdin, so normal operation is independent of whether Claude itself was launched from PowerShell, Command Prompt, Windows Terminal, or Git Bash. Manual test quoting remains shell-specific.
