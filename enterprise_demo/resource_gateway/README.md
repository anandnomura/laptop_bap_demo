# Resource gateway

Python demo enforcement gateway. It independently checks grant signature, expiry, revocation, audience and action/resource/run bindings before forwarding to the protected resource.

Run and verify through the full demo:

```powershell
enterprise_demo\start-enterprise-demo.bat
enterprise_demo\run-enterprise-smoke-test.bat
```

Stakeholder evidence: `GRANT_VALID` for authorized access and `GRANT_REJECTED` for a fictitious token. This gateway—not the dashboard or model—is the final authorization check before resource access.
