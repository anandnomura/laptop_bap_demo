# Enterprise binary-signing runbook

The local demo can add an Authenticode signature using a short-lived self-issued certificate. That proves packaging and caller-verification behavior; it does not establish enterprise publisher trust.

## Production objective

Sign these administrator-deployed artifacts:

- `claude_guard.exe`
- `bap_connector_service.exe`
- `bap_resource_client.exe`
- the MSI/MSIX installer and every privileged support or diagnostic utility

Do not sign or distribute `claude_guard_lab.exe`, test connectors, bypass utilities, private keys, demo certificates, or local orchestration scripts as production artifacts.

## Certificate requirements

Use an enterprise code-signing certificate with the Code Signing EKU. The private key should be non-exportable and held by an HSM-backed signing service such as an internal signing platform, Azure Trusted Signing, an approved cloud KMS/HSM integration, or a physical enterprise HSM. Build agents submit hashes or artifacts to the signing service; they do not receive the private key.

Maintain separate identities for development, pre-production, and production signing. WDAC production policy must trust only the production publisher and approved product/file attributes.

## Release pipeline

1. Build from an approved, immutable commit in a protected CI environment.
2. Restore dependencies from allowlisted, integrity-checked repositories.
3. Produce SBOM, dependency inventory, compiler/build logs, and reproducible artifact hashes.
4. Run unit, integration, SAST, dependency, malware, and end-to-end enforcement tests.
5. Submit release artifacts to the protected signing service.
6. Authenticode-sign with SHA-256 and an enterprise-approved RFC 3161 timestamp authority.
7. Verify the full certificate chain, EKU, timestamp, publisher subject, and file signature after signing.
8. Record SHA-256, signer thumbprint, source commit, pipeline run, SBOM digest, approvers, and release version in the release ledger.
9. Publish through endpoint management as a managed installer.
10. Update WDAC/App Control publisher/file rules through a staged, signed policy release.

Example verification on Windows:

```powershell
Get-AuthenticodeSignature 'C:\Program Files\Company\BAP\claude_guard.exe' |
  Format-List Status,StatusMessage,SignerCertificate,TimeStamperCertificate

Get-FileHash 'C:\Program Files\Company\BAP\claude_guard.exe' -Algorithm SHA256
```

Production acceptance requires `Status: Valid`, the expected publisher subject, an approved chain, and a trusted timestamp.

## Runtime enforcement

Signing alone does not prevent replacement or use of another signed tool. Combine it with:

- Program Files ACLs: SYSTEM and support administrators write; developers read/execute only.
- WDAC/App Control allow rules scoped to the approved publisher and product/file attributes.
- Connector-side verification of named-pipe client PID, actual image path, signer chain, product name, version floor, and optionally release-ledger hash.
- Client-side verification that the pipe server is the approved connector service.
- Endpoint monitoring for signature failures, file changes, service changes, and policy drift.

Do not trust a self-reported signer, path, hash, or version from a request payload. Measure the connecting process independently.

## Rotation and revocation

Document primary and emergency signing certificates, expiration, rollover overlap, revocation owners, and emergency WDAC policy deployment. If a signing key or signed build is compromised:

1. Revoke the certificate or deny the affected signer/file attributes.
2. Block compromised hashes with emergency WDAC policy.
3. Stop connector acceptance of affected versions.
4. Deploy a newly signed release and policy.
5. preserve central evidence and investigate every execution of the affected artifact.

## Demo signing

After building and generating the demo PKI:

```powershell
enterprise_demo\demo_pki\sign-demo-binaries.ps1
```

The script imports the demo PFX into the current-user personal store only long enough to sign, removes it afterward, and embeds signatures in the three demo executables. Because the certificate is self-issued and is not timestamped, Windows may report `UnknownError`; the demo connector verifies the embedded signer subject. Never install the demo CA or code-signing certificate into enterprise trust stores.
