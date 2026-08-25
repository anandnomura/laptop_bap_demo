# Protected resource simulator

Python database-like target used to prove target-side enforcement. It accepts calls only from the resource gateway path.

Negative test after starting the enterprise demo:

```powershell
py -3 enterprise_demo\bap_resource_client\direct_resource_client.py
```

Expected: HTTP 403-style error `Resource gateway required` and dashboard event `DIRECT_ACCESS_DENIED`. The full smoke test also proves no denied request produces `RESOURCE_EXECUTED`.
