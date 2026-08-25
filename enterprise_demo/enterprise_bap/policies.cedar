// Enterprise BAP demo policy set. Cedar is deny-by-default: no matching permit means DENY.

@id("forbid-production-from-laptop-agents")
forbid (
    principal,
    action,
    resource is BAP::DataStore
)
when {
    resource.environment == "production" && context.agentClass == "laptop-agent"
};

@id("forbid-destructive-database-actions")
forbid (
    principal,
    action == BAP::Action::"databaseDelete",
    resource
);

@id("permit-development-customer-read")
permit (
    principal,
    action == BAP::Action::"databaseRead",
    resource == BAP::DataStore::"dev-customer-db"
)
when {
    context.registered &&
    context.deviceManaged &&
    (context.agent == "claude-code" || context.agent == "scale-probe")
};

// A write is executable only after independent approval has been recorded.
@id("permit-approved-development-customer-write")
permit (
    principal,
    action == BAP::Action::"databaseWrite",
    resource == BAP::DataStore::"dev-customer-db"
)
when {
    context.registered &&
    context.deviceManaged &&
    context.humanApproved &&
    context.agent == "claude-code"
};

// This meta-permission means an approval may be requested; it does not permit the write.
@id("permit-development-write-approval-request")
permit (
    principal,
    action == BAP::Action::"requestDatabaseWriteApproval",
    resource == BAP::DataStore::"dev-customer-db"
)
when {
    context.registered &&
    context.deviceManaged &&
    context.agent == "claude-code"
};
