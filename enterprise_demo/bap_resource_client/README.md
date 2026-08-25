# BAP resource client

Signed C#/.NET demo adapter for resource operations. It sends a session-bound operation to the laptop connector over the named pipe. It never receives the BAP grant or mTLS private key.

After building and starting the full enterprise demo, use it through Claude or the smoke test. Direct manual execution without a registered/authorized session must fail:

```powershell
enterprise_demo\bap_resource_client\publish\bap_resource_client.exe read customer-123 --bap-session missing-session
```

Direct-resource negative case:

```powershell
py -3 enterprise_demo\bap_resource_client\direct_resource_client.py
```

Full verification:

```powershell
enterprise_demo\run-enterprise-smoke-test.bat
```
