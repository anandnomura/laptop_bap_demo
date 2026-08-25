# Shared central-demo library

Python helpers for paths, TLS, HTTP JSON, SQLite audit state, and asymmetric grants. This directory is a library and has no standalone demo command.

Syntax and integration are verified by:

```powershell
py -3 -m compileall -q enterprise_demo\common
enterprise_demo\run-enterprise-smoke-test.bat
```

Production replaces SQLite/file keys with durable stores and HSM/KMS-backed signing.
