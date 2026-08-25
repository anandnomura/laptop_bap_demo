# Laptop connector service

Windows-specific C#/.NET endpoint service. It owns the named pipe, verifies signed callers, registers agent runs, calls central BAP over mTLS, retains grants, and calls the resource gateway.

Do not normally run it alone. From the repository root:

```powershell
powershell -ExecutionPolicy Bypass -File enterprise_demo\orchestration\build_demo.ps1
enterprise_demo\start-enterprise-demo.bat
enterprise_demo\run-enterprise-smoke-test.bat
```

Standalone health is checked through the signed guard:

```powershell
enterprise_demo\claude_guard\publish\claude_guard.exe --health
```

Stakeholder evidence: dashboard events `PIPE_CLIENT_REJECTED`, `SESSION_REGISTERED`, `TOOL_INTERCEPTED`, and connector mTLS events. Stop with `enterprise_demo\stop-enterprise-demo.bat`.
