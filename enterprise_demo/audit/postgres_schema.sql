-- Reference PostgreSQL 16+ operational audit schema. Apply through reviewed migrations.
CREATE SCHEMA IF NOT EXISTS bap_audit;

CREATE TABLE bap_audit.event (
    occurred_at_utc timestamptz NOT NULL,
    event_id uuid NOT NULL,
    received_at_utc timestamptz NOT NULL DEFAULT clock_timestamp(),
    schema_version text NOT NULL DEFAULT '1.0',
    source text NOT NULL,
    kind text NOT NULL,
    message text NOT NULL,
    level text NOT NULL CHECK (level IN ('info','success','warning','error')),
    outcome text,
    trace_id text, request_id text, decision_id text, execution_id text,
    session_id text, agent_run_id text,
    user_id text, device_id text, agent_type text, agent_version text, tool_name text,
    task_summary text,
    action text, resource text, resource_key text,
    decision text CHECK (decision IS NULL OR decision IN ('ALLOW','REQUIRE_APPROVAL','DENY')),
    decision_reason text,
    policy_bundle_id text, policy_revision text, policy_rule_id text, policy_bundle_sha256 char(64),
    approval_request_id text, approver_id text,
    grant_id text, grant_expires_at timestamptz,
    http_status integer, client_process_id integer, client_executable text,
    client_signer_subject text, mtls_subject text,
    request_payload_hash char(64), result_payload_hash char(64),
    details jsonb NOT NULL DEFAULT '{}'::jsonb,
    chain_partition text NOT NULL,
    chain_sequence bigint NOT NULL,
    previous_event_hash char(64) NOT NULL,
    event_hash char(64) NOT NULL,
    PRIMARY KEY (occurred_at_utc, event_id),
    UNIQUE (occurred_at_utc, chain_partition, chain_sequence),
    CHECK (jsonb_typeof(details) = 'object')
) PARTITION BY RANGE (occurred_at_utc);

-- Create future monthly partitions before traffic arrives. Example only:
CREATE TABLE IF NOT EXISTS bap_audit.event_2026_08 PARTITION OF bap_audit.event
FOR VALUES FROM ('2026-08-01T00:00:00Z') TO ('2026-09-01T00:00:00Z');

CREATE INDEX event_request_idx ON bap_audit.event (request_id, occurred_at_utc);
CREATE INDEX event_trace_idx ON bap_audit.event (trace_id, occurred_at_utc);
CREATE INDEX event_user_idx ON bap_audit.event (user_id, occurred_at_utc DESC);
CREATE INDEX event_resource_idx ON bap_audit.event (resource, occurred_at_utc DESC);
CREATE INDEX event_decision_idx ON bap_audit.event (decision, occurred_at_utc DESC);
CREATE INDEX event_grant_idx ON bap_audit.event (grant_id, occurred_at_utc);
CREATE INDEX event_execution_idx ON bap_audit.event (execution_id, occurred_at_utc);
CREATE INDEX event_details_gin_idx ON bap_audit.event USING gin (details jsonb_path_ops);

CREATE OR REPLACE FUNCTION bap_audit.reject_mutation() RETURNS trigger LANGUAGE plpgsql AS $$
BEGIN RAISE EXCEPTION 'BAP audit evidence is append-only'; END $$;
CREATE TRIGGER event_no_update BEFORE UPDATE ON bap_audit.event
FOR EACH ROW EXECUTE FUNCTION bap_audit.reject_mutation();
CREATE TRIGGER event_no_delete BEFORE DELETE ON bap_audit.event
FOR EACH ROW EXECUTE FUNCTION bap_audit.reject_mutation();

-- Production roles: ingest can INSERT only; readers SELECT only. Table owners are
-- break-glass identities, never application identities.
REVOKE ALL ON bap_audit.event FROM PUBLIC;
-- GRANT INSERT ON bap_audit.event TO bap_audit_ingest;
-- GRANT SELECT ON bap_audit.event TO bap_audit_reader;
