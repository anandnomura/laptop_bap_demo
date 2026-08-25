# Production deployment blueprint

## Endpoint deployment

Install these signed .NET 8 Windows binaries under `C:\Program Files\Company\BAP\` using the enterprise endpoint-management system:

- `bap_connector_service.exe` as an auto-start Windows service under a dedicated virtual/service account;
- `claude_guard.exe` as the managed Claude hook adapter;
- signed resource adapters only where an existing client cannot use the connector SDK/MCP path.

The service owns a named pipe with an explicit ACL limited to LocalSystem, the service SID, and approved interactive users. It verifies caller PID, executable path, publisher chain, file identity, and signature with WinVerifyTrust. Developers cannot modify Program Files, service configuration, machine certificate stores, WDAC/App Control policy, or managed agent settings.

Store the connector mTLS certificate as a non-exportable machine key restricted to the service identity. Rotate it through enterprise PKI/MDM. Production has no TCP port 11022; local diagnostics are administrator-enabled, time-limited, audited, and never an authorization interface.

## Central deployment

Run the Python BAP API, approval coordinator, grant service, audit ingestion, and resource gateway control plane as separate scalable Linux container workloads. Use an ingress/API gateway for mTLS termination and workload identity. Run at least three replicas across failure zones.

Replace demo SQLite with PostgreSQL for authoritative state, Redis only for bounded caches/rate limits, and Kafka or the company event platform for durable audit. Keep grant-signing keys in HSM/KMS. Use a central Cedar engine/sidecar; do not spawn the Cedar CLI per production request.

## Required network segmentation

| Source | Destination | Rule |
|---|---|---|
| Developer laptop connector service | BAP ingress and approved resource gateways | Allow TCP 443 through corporate proxy/VPN with device mTLS |
| Other laptop processes | BAP/resource gateway | Deny where process-aware controls are available; gateway still requires connector identity |
| Any laptop/VPN user subnet | Database, cloud control plane, privileged API, production service admin interface | Deny |
| Resource gateway subnet/workload identity | Registered protected resource | Allow only required port/API/action |
| Protected resource | General laptop subnets | Deny and log |
| BAP workload | Identity, device posture, policy distribution, approval, KMS, audit stores | Allow narrowly by service identity |

Network enforcement must exist at VPN/firewall/security-group/service-mesh and target levels. DNS hiding or hooks alone are not segmentation.

## Zero standing privilege

The developer and agent hold no reusable production credential. A registered agent run receives a policy decision for one normalized action and resource. If permitted, the connector holds a signed grant lasting about one minute. The gateway revalidates it at execution, and session close/revocation invalidates it. Authority therefore exists only for the approved action, resource, principal, agent run, and short time window.

## Rollout phases

1. Observe-only inventory: classify tools/resources and compare proposed decisions without granting access.
2. Development read paths: enforce BAP with gateway-only networking and negative-case tests.
3. Approval-required development writes: integrate the enterprise approval service.
4. Broader agents: certify Cursor/Copilot adapters against the same connector contract.
5. Sensitive resources: onboard resource gateways, policy-owner workflow, and incident response.
6. Production enforcement: block legacy direct paths before enabling BAP grants.

See [SIGNING_RUNBOOK.md](SIGNING_RUNBOOK.md) for production signing and [POLICY_MODEL.md](POLICY_MODEL.md) for Cedar governance.
