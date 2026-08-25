# Enterprise BAP policy model

## Where an allow or deny comes from

The agent, ClaudeGuard, and laptop connector do not decide authority. They assemble evidence and ask the central BAP. The central BAP converts that evidence into a Cedar authorization request:

| Cedar element | BAP meaning | Production source |
|---|---|---|
| Principal | Human on whose behalf the agent is acting | Identity claims already validated by the enterprise Claude gateway; LDAP/Swarm membership from an authoritative identity service |
| Action | Normalized business operation such as `databaseRead` | Signed adapter/resource catalog mapping, never free-form model text |
| Resource | Stable enterprise resource such as `DataStore::"dev-customer-db"` | CMDB/resource catalog with owner, environment, classification, and allowed gateway |
| Context | This particular request: agent, run, managed-device state, task, approval state | Connector attestation, agent registry, MDM/EDR posture, approval service, and request metadata |

Cedar calls this the principal/action/resource/context, or PARC, request. Cedar is deny by default: without a matching `permit`, the result is `DENY`; any matching `forbid` overrides a permit.

## Files used by this demo

- [policies.cedar](enterprise_bap/policies.cedar) contains the actual allow/forbid rules.
- [bap.cedarschema](enterprise_bap/bap.cedarschema) defines valid principals, resources, actions, and context fields.
- [resources.cedarentities.json](enterprise_bap/resources.cedarentities.json) is the demo resource catalog.
- [policy-bundle.json](enterprise_bap/policy-bundle.json) supplies bundle version, pinned Cedar version, and grant lifetime.
- [policy_engine.py](enterprise_bap/policy_engine.py) validates and invokes the official Cedar CLI. It is orchestration code, not the source of allow rules.

The build downloads the pinned official Cedar CLI and verifies its SHA-256 checksum. The downloaded executable is under `enterprise_demo/runtime/` and is excluded from Git.

## Demo decisions

| Request | Cedar outcome | BAP outcome | Policy ID |
|---|---|---|---|
| Claude reads `dev-customer-db` | Permit | `ALLOW` plus 60-second grant | `permit-development-customer-read` |
| Claude writes `dev-customer-db`, not yet approved | Write denied; approval-request action permitted | `REQUIRE_APPROVAL`; no executable grant | `permit-development-write-approval-request` |
| Same write after approval | Permit with `humanApproved=true` | `ALLOW` plus 60-second grant | `permit-approved-development-customer-write` |
| Delete any database record | Forbid | `DENY`; no grant | `forbid-destructive-database-actions` |
| Laptop agent reads production | Forbid | `DENY`; no grant | `forbid-production-from-laptop-agents` |
| Anything not described | No permit | `DENY`; no grant | `default-deny` |

Approval is deliberately modeled as a separate Cedar meta-permission. Permission to request approval is not permission to execute. After approval, BAP evaluates the original write again with verified approval context; policy changes between request and approval therefore take effect.

## Production policy lifecycle

1. Resource owners register stable resource IDs and attributes in the resource catalog.
2. Security/platform teams define the Cedar schema and reusable policy templates.
3. Resource owners submit narrowly scoped policy changes by pull request.
4. CI parses and validates every policy against the schema, runs allow/deny regression cases, checks invariants, and rejects unbounded permits.
5. Required security and resource-owner reviewers approve the change.
6. CI signs an immutable policy bundle containing policies, schema, entity snapshot/reference, version, and hashes.
7. BAP replicas accept bundles only from the policy distribution service and only with a trusted signature.
8. Replicas activate a bundle atomically, report its version/hash, and retain the prior version for rollback.
9. Every decision records the bundle version, matched permit/forbid IDs, request correlation ID, and identity/resource evidence versions.
10. Policy changes and unusual deny/allow patterns stream to the central audit/SIEM service.

Production must not let an endpoint, developer, agent prompt, or resource client submit its own groups, device posture, resource classification, approval status, or policy. BAP obtains those attributes from authoritative systems or signed attestations.

## Production Cedar runtime

The CLI subprocess is intentionally a laptop demo mechanism. At production volume, keep the Python BAP API but evaluate Cedar through one of these central, non-Windows choices:

- an in-process or sidecar Cedar engine built from the official Rust library;
- a horizontally scaled Cedar Local Agent/policy decision service;
- an approved managed Cedar service if company architecture permits it.

Cache immutable policy bundles and low-volatility entity data, not decisions. Identity, approval, revocation, and device-posture evidence must have explicit freshness limits. Evaluation errors, missing entities, stale mandatory attributes, and unavailable policy infrastructure fail closed.

## Who configures what

| Owner | Configuration responsibility |
|---|---|
| Identity team | Stable user IDs and Swarm/group claims; TeaToken authentication remains at the enterprise Claude gateway |
| Endpoint team | Managed-device identity, connector certificate, signed binaries, service/pipe ACL, and managed agent hooks |
| BAP platform team | Cedar schema, policy runtime, bundle distribution, grant signing, audit, availability, and safe rollback |
| Resource owner | Resource registration, classification, actions, approvers, and proposed policy bindings |
| Network/security team | Gateway-only routes and denial of laptop-to-resource direct paths |
| Agent integration team | Vendor-event normalization and decision translation; no authorization rules in the adapter |

References: [Cedar authorization and PARC](https://docs.cedarpolicy.com/auth/authorization.html), [Cedar policy syntax](https://docs.cedarpolicy.com/policies/syntax-policy.html), and [schema validation](https://docs.cedarpolicy.com/policies/validation.html).
