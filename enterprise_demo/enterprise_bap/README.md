# Enterprise BAP service

Horizontally scalable Python authorization API. This is where Cedar policy is evaluated and short-lived grants are issued. Allow rules are in `policies.cedar`, not in the agent, guard, or connector.

Policy files:

- `policies.cedar`: permits and forbids;
- `bap.cedarschema`: valid request/entity contract;
- `resources.cedarentities.json`: demo resource catalog;
- `policy-bundle.json`: bundle/Cedar version and grant lifetime.

Validate policy from the repository root:

```powershell
powershell -ExecutionPolicy Bypass -File enterprise_demo\orchestration\install_cedar_cli.ps1
enterprise_demo\runtime\tools\cedar-4.12.0\cedar.exe validate --policies enterprise_demo\enterprise_bap\policies.cedar --schema enterprise_demo\enterprise_bap\bap.cedarschema --schema-format cedar --deny-warnings
```

Run and smoke-test through the complete architecture:

```powershell
enterprise_demo\start-enterprise-demo.bat
enterprise_demo\run-enterprise-smoke-test.bat
```

Stakeholder evidence: `POLICY_MATCHED`, matched Cedar policy ID, bundle revision/hash, `GRANT_ISSUED`, and `POLICY_DENY` on the dashboard.
