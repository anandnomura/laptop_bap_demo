# BAP mTLS front door

Python demo ingress that requires the connector client certificate and round-robins requests across two BAP replicas. It is started and tested only as part of the complete demo:

```powershell
enterprise_demo\start-enterprise-demo.bat
enterprise_demo\run-enterprise-smoke-test.bat
```

Stakeholder evidence: requests reach both `BAP REPLICA 1` and `BAP REPLICA 2`, while a TLS client without the connector certificate is rejected. Production replaces this process with the enterprise ingress/API gateway.
