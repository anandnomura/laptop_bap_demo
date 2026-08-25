# Production audit and evidence model

Every protected request has one `trace_id` for the agent session, one `request_id` for the proposed action, one or more `decision_id` values when approval causes re-evaluation, and an `execution_id` only if a gateway attempts execution. Search by any of these IDs to reconstruct the timeline.

The demo implements this contract in `common/audit_store.py` and exposes it at:

- `GET /api/access`: one normalized row per resource request;
- `GET /api/audit`: immutable events, filterable by identity, request, action, resource, decision, policy, kind, or time;
- `GET /api/integrity`: verifies the local SHA-256 hash chain;
- `GET /api/export`: downloads the filtered evidence as JSON Lines.

The dashboard is at `http://127.0.0.1:11445`. Example searches:

```powershell
Invoke-RestMethod 'http://127.0.0.1:11445/api/access?user_id=User'
Invoke-RestMethod 'http://127.0.0.1:11445/api/audit?decision=DENY'
Invoke-RestMethod 'http://127.0.0.1:11445/api/integrity'
Invoke-WebRequest 'http://127.0.0.1:11445/api/export?action=database.read' -OutFile bap-audit.jsonl
```

## Required evidence

The canonical envelope records when and where the event was received; user, managed device, agent, run, session, and task; normalized action, resource, and key; policy bundle/rule/revision; decision and reason; approval, approver, grant, and execution IDs; mTLS/caller evidence; HTTP/outcome data; hashes of request/result payloads; and tamper-evidence hashes. Secret values and grant tokens are never audit fields.

The connector durably queues audit events if central ingestion is temporarily unavailable. It fails closed before a protected operation when required audit evidence cannot be delivered or queued. A result event is queued after execution rather than hiding a successfully completed action from the caller.

## Production implementation

SQLite and the localhost dashboard are demonstration components. Production should use:

1. authenticated, rate-limited audit ingestion separate from the decision response path;
2. Kafka or the enterprise event platform with replication and idempotency by `event_id`;
3. partitioned PostgreSQL for operational search using [postgres_schema.sql](postgres_schema.sql) as a starting contract;
4. continuous export to immutable/WORM object storage and the enterprise SIEM;
5. SSO/RBAC so developers can see their own requests, security/auditors have scoped read access, and only the audit service writes;
6. retention, legal hold, privacy classification, backup/restore, clock synchronization, and alerting owned by Security/Audit;
7. daily signed checkpoints anchored outside the database. A database-admin-controlled hash chain alone is not sufficient non-repudiation.

Recommended alerts include fail-closed audit outbox growth, hash/checkpoint mismatch, repeated direct-path attempts, fictitious grants, denied production actions, replay/binding failures, policy rollback, and unexpected connector identities.

The JSON contract is in [audit_event.schema.json](audit_event.schema.json). Never place prompts, database values, grant JWTs, TeaTokens, authorization headers, or private keys in evidence. Store bounded task summaries and payload hashes instead.
