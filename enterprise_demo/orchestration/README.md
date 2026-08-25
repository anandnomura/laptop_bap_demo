# Build and orchestration

Run every command from the repository root.

Build binaries, install the pinned/checksummed Cedar CLI, generate demo PKI, and demo-sign binaries:

```powershell
powershell -ExecutionPolicy Bypass -File enterprise_demo\orchestration\build_demo.ps1
```

Start all seven processes and open the dashboard:

```powershell
enterprise_demo\start-enterprise-demo.bat
```

Audit/grant state is preserved by default. To intentionally start clean, use `py -3 enterprise_demo\orchestration\start_demo.py --reset-state`; prior files are archived under `enterprise_demo\runtime\archive\`.

Full smoke test:

```powershell
enterprise_demo\run-enterprise-smoke-test.bat
```

Stop and verify cleanup:

```powershell
enterprise_demo\stop-enterprise-demo.bat
```

The smoke test covers named-pipe identity, mTLS, replica distribution, Cedar allow/approval/deny, grant execution, missing/fictitious grants, direct-resource denial, correlated search, secret exclusion, hash-chain integrity, dashboard evidence, and absence of port 11022.
