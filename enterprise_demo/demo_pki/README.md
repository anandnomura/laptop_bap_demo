# Demo PKI and signing

Generates local demo CA, mTLS certificates, grant-signing keys, and a self-issued Authenticode certificate. The standard build invokes it automatically:

```powershell
powershell -ExecutionPolicy Bypass -File enterprise_demo\orchestration\build_demo.ps1 -RegeneratePki
```

Generated private keys/certificates live under `enterprise_demo/runtime/` and are ignored by Git. They are not production credentials. See `..\SIGNING_RUNBOOK.md` for enterprise HSM/PKI signing and rotation.
