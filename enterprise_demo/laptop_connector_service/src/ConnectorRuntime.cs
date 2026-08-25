using System.Collections.Concurrent;
using System.Text.Json.Nodes;

namespace Company.Bap.ConnectorService;

internal sealed class ConnectorRuntime(EnterpriseClient enterprise)
{
    private readonly ConcurrentDictionary<string, SessionState> _sessions = new(StringComparer.Ordinal);
    private readonly ConcurrentDictionary<string, AuthorizationState> _authorizations = new(StringComparer.Ordinal);

    public async Task<JsonObject> DispatchAsync(string path, JsonObject payload, ClientIdentity client)
    {
        try
        {
            return path switch
            {
                "/health" => PipeServer.Response(200, new JsonObject
                {
                    ["ok"] = true,
                    ["service"] = "bap-connector-service",
                    ["transport"] = "windows-named-pipe"
                }),
                "/session/start" => await StartSessionAsync(payload, client),
                "/intent" => await CaptureIntentAsync(payload, client),
                "/hook/pre-tool" => await AuthorizeToolAsync(payload, client),
                "/hook/permission" => await RecordHookAsync("PERMISSION_REQUEST", payload, client),
                "/hook/post-tool" => await RecordHookAsync("TOOL_COMPLETED", payload, client),
                "/session/end" => await EndSessionAsync(payload, client),
                "/resource/execute" => await ExecuteResourceAsync(payload, client),
                _ => await UnknownPathAsync(path, payload, client)
            };
        }
        catch (Exception exception) when (exception is HttpRequestException or TaskCanceledException)
        {
            await enterprise.AuditAsync(
                "ENTERPRISE_SERVICE_UNAVAILABLE",
                "Denied operation because an enterprise service was unavailable",
                new JsonObject { ["path"] = path, ["error"] = exception.Message },
                "error");
            if (path == "/hook/pre-tool")
            {
                return PipeServer.Response(200, new JsonObject
                {
                    ["decision"] = "DENY",
                    ["reason"] = "Enterprise BAP unavailable; connector failed closed"
                });
            }
            return PipeServer.Response(503, new JsonObject { ["error"] = "Enterprise service unavailable; failed closed" });
        }
        catch (Exception exception)
        {
            await enterprise.AuditAsync("CONNECTOR_INTERNAL_ERROR", "Connector failed closed on an internal error", new JsonObject { ["request_id"] = "req-" + Guid.NewGuid().ToString("N"), ["request_path"] = path, ["decision"] = "DENY", ["decision_reason"] = "Connector internal error", ["outcome"] = "DENIED", ["error_type"] = exception.GetType().Name }, "error");
            return PipeServer.Response(500, new JsonObject { ["error"] = "Connector internal error; failed closed" });
        }
    }

    public Task RecordRejectedClientAsync(ClientIdentity client, string path, string reason) =>
        enterprise.AuditAsync(
            "PIPE_CLIENT_REJECTED",
            $"Rejected named-pipe caller: {reason}",
            new JsonObject { ["request_id"] = "req-" + Guid.NewGuid().ToString("N"), ["request_path"] = path, ["decision"] = "DENY", ["decision_reason"] = reason, ["outcome"] = "DENIED", ["client"] = ClientDetails(client, path) },
            "error");

    public Task RecordPipeFailureAsync(ClientIdentity? client, string path, Exception exception) =>
        enterprise.AuditAsync(
            "PIPE_PROTOCOL_DENIED",
            "Rejected malformed or failed named-pipe request",
            new JsonObject { ["request_id"] = "req-" + Guid.NewGuid().ToString("N"), ["request_path"] = path, ["decision"] = "DENY", ["decision_reason"] = "Named-pipe protocol failure", ["outcome"] = "DENIED", ["error_type"] = exception.GetType().Name, ["client"] = client is null ? null : ClientDetails(client, path) },
            "error");

    private async Task<JsonObject> UnknownPathAsync(string path, JsonObject payload, ClientIdentity client)
    {
        await enterprise.AuditAsync(
            "UNKNOWN_CONNECTOR_ROUTE_DENIED",
            $"Rejected unknown connector route {path}",
            new JsonObject { ["request_id"] = "req-" + Guid.NewGuid().ToString("N"), ["request_path"] = path, ["decision"] = "DENY", ["decision_reason"] = "Unknown connector route", ["outcome"] = "DENIED", ["client"] = ClientDetails(client, path) },
            "error");
        return PipeServer.Response(404, new JsonObject { ["error"] = "Unknown connector request path" });
    }

    private async Task<JsonObject> StartSessionAsync(JsonObject payload, ClientIdentity client)
    {
        var sessionId = String(payload, "session_id");
        if (string.IsNullOrWhiteSpace(sessionId))
        {
            await enterprise.AuditAsync("SESSION_REGISTRATION_DENIED", "Rejected session without an identifier", new JsonObject { ["request_id"] = "req-" + Guid.NewGuid().ToString("N"), ["decision"] = "DENY", ["decision_reason"] = "Claude session_id is required", ["outcome"] = "DENIED", ["client"] = ClientDetails(client, "/session/start") }, "error");
            return PipeServer.Response(400, new JsonObject { ["error"] = "Claude session_id is required" });
        }
        var state = new SessionState(
            sessionId,
            "cc-run-" + Guid.NewGuid().ToString("N")[..12],
            "trc-" + Guid.NewGuid().ToString("N"),
            String(payload, "user", Environment.UserName),
            Environment.MachineName,
            String(payload, "cwd"),
            "Task not captured yet");
        _sessions[sessionId] = state;
        var details = SessionDetails(state, client);
        details["hook_client"] = payload["client_metadata"]?.DeepClone();
        await enterprise.AuditAsync("SESSION_REGISTERED", $"Registered Claude session {sessionId} as {state.AgentRun}", details, "success");
        return PipeServer.Response(200, new JsonObject { ["ok"] = true, ["session"] = details.DeepClone() });
    }

    private async Task<JsonObject> CaptureIntentAsync(JsonObject payload, ClientIdentity client)
    {
        var sessionId = String(payload, "session_id");
        if (!_sessions.TryGetValue(sessionId, out var state))
        {
            await enterprise.AuditAsync("UNREGISTERED_SESSION_DENIED", "Rejected task intent for an unregistered session", new JsonObject { ["request_id"] = "req-" + Guid.NewGuid().ToString("N"), ["session_id"] = sessionId, ["decision"] = "DENY", ["decision_reason"] = "Agent session is not registered", ["outcome"] = "DENIED", ["client"] = ClientDetails(client, "/intent") }, "error");
            return PipeServer.Response(403, new JsonObject { ["error"] = "Agent session is not registered" });
        }
        var prompt = String(payload, "prompt", String(payload, "user_prompt"));
        state.Task = prompt.Length > 300 ? prompt[..300] : prompt;
        await enterprise.AuditAsync(
            "TASK_INTENT_CAPTURED",
            $"Captured task intent for {state.AgentRun}",
            new JsonObject
            {
                ["session_id"] = sessionId,
                ["trace_id"] = state.TraceId,
                ["agent_run"] = state.AgentRun,
                ["task_summary"] = state.Task.Length > 120 ? state.Task[..120] : state.Task,
                ["client"] = ClientDetails(client, "/intent")
            });
        return PipeServer.Response(200, new JsonObject { ["ok"] = true });
    }

    private async Task<JsonObject> AuthorizeToolAsync(JsonObject payload, ClientIdentity client)
    {
        var sessionId = String(payload, "session_id");
        var toolName = String(payload, "tool_name");
        if (!_sessions.TryGetValue(sessionId, out var session))
        {
            var rejectedRequestId = "req-" + Guid.NewGuid().ToString("N");
            await enterprise.AuditAsync(
                "UNREGISTERED_SESSION_DENIED",
                $"Denied {toolName}: session is not registered",
                new JsonObject { ["trace_id"] = "trc-" + Guid.NewGuid().ToString("N"), ["request_id"] = rejectedRequestId, ["session_id"] = sessionId, ["tool_name"] = toolName, ["decision"] = "DENY", ["decision_reason"] = "Agent session is not registered with the laptop connector", ["outcome"] = "DENIED" },
                "error");
            return PipeServer.Response(200, new JsonObject
            {
                ["decision"] = "DENY",
                ["reason"] = "Agent session is not registered with the laptop connector"
            });
        }

        var classification = Classify(toolName, payload["tool_input"] as JsonObject ?? new JsonObject());
        var requestId = String(payload, "tool_use_id");
        if (string.IsNullOrWhiteSpace(requestId)) requestId = "req-" + Guid.NewGuid().ToString("N");
        var requestContext = new JsonObject
        {
            ["trace_id"] = session.TraceId,
            ["request_id"] = requestId,
            ["session_id"] = sessionId,
            ["agent_run"] = session.AgentRun,
            ["user"] = session.User,
            ["device"] = session.Device,
            ["agent"] = "claude-code",
            ["task"] = session.Task,
            ["tool_name"] = toolName,
            ["category"] = classification.Category,
            ["action"] = classification.Action,
            ["resource"] = classification.Resource,
            ["client"] = ClientDetails(client, "/hook/pre-tool")
        };
        await enterprise.AuditAsync(
            "TOOL_INTERCEPTED",
            $"Intercepted {toolName}: {classification.Summary}",
            requestContext.DeepClone() as JsonObject ?? new());

        if (classification.Category == "LOCAL")
        {
            await enterprise.AuditAsync("TOOL_DECISION", "Local workspace action allowed", new JsonObject { ["trace_id"] = session.TraceId, ["request_id"] = requestId, ["session_id"] = sessionId, ["agent_run"] = session.AgentRun, ["user"] = session.User, ["device"] = session.Device, ["agent"] = "claude-code", ["tool_name"] = toolName, ["decision"] = "ALLOW", ["decision_reason"] = "Local workspace action allowed", ["outcome"] = "AUTHORIZED" }, "success");
            return PipeServer.Response(200, new JsonObject
            {
                ["decision"] = "ALLOW",
                ["reason"] = "Local workspace action allowed"
            });
        }
        if (classification.Category == "BYPASS")
        {
            await enterprise.AuditAsync(
                "DIRECT_PATH_BLOCKED",
                "Blocked a direct resource access path",
                new JsonObject { ["trace_id"] = session.TraceId, ["request_id"] = requestId, ["session_id"] = sessionId, ["agent_run"] = session.AgentRun, ["user"] = session.User, ["device"] = session.Device, ["agent"] = "claude-code", ["summary"] = classification.Summary, ["decision"] = "DENY", ["decision_reason"] = "Direct resource access is blocked", ["outcome"] = "DENIED" },
                "error");
            return PipeServer.Response(200, new JsonObject
            {
                ["decision"] = "DENY",
                ["reason"] = "Direct resource access is blocked; use the signed BAP resource client"
            });
        }

        var (status, decision) = await enterprise.BapAsync("authorize", new JsonObject
        {
            ["user"] = session.User,
            ["device"] = session.Device,
            ["agent"] = "claude-code",
            ["agent_run"] = session.AgentRun,
            ["trace_id"] = session.TraceId,
            ["request_id"] = requestId,
            ["task"] = session.Task,
            ["action"] = classification.Action,
            ["resource"] = classification.Resource
        });
        if (status != 200)
        {
            await enterprise.AuditAsync("TOOL_DECISION", "Enterprise BAP authorization failed", new JsonObject { ["trace_id"] = session.TraceId, ["request_id"] = requestId, ["session_id"] = sessionId, ["agent_run"] = session.AgentRun, ["user"] = session.User, ["device"] = session.Device, ["agent"] = "claude-code", ["action"] = classification.Action, ["resource"] = classification.Resource, ["decision"] = "DENY", ["decision_reason"] = "Enterprise BAP authorization failed; connector failed closed", ["http_status"] = status, ["outcome"] = "DENIED" }, "error");
            return PipeServer.Response(200, new JsonObject
            {
                ["decision"] = "DENY",
                ["reason"] = "Enterprise BAP authorization failed; connector failed closed"
            });
        }
        await enterprise.AuditAsync(
            "TOOL_DECISION",
            $"Returned {String(decision, "decision", "DENY")} to the agent",
            new JsonObject { ["trace_id"] = session.TraceId, ["request_id"] = requestId, ["decision_id"] = String(decision, "decision_id"), ["session_id"] = sessionId, ["agent_run"] = session.AgentRun, ["user"] = session.User, ["device"] = session.Device, ["agent"] = "claude-code", ["tool_name"] = toolName, ["action"] = classification.Action, ["resource"] = classification.Resource, ["decision"] = String(decision, "decision", "DENY"), ["decision_reason"] = String(decision, "reason"), ["policy"] = decision["policy"]?.DeepClone(), ["approval_request_id"] = String(decision, "approval_request_id"), ["grant_id"] = (decision["grant"] as JsonObject)?["grant_id"]?.DeepClone(), ["outcome"] = String(decision, "decision") == "DENY" ? "DENIED" : String(decision, "decision") == "REQUIRE_APPROVAL" ? "PENDING_APPROVAL" : "AUTHORIZED" },
            String(decision, "decision") == "DENY" ? "error" : String(decision, "decision") == "REQUIRE_APPROVAL" ? "warning" : "success");
        _authorizations[sessionId] = new AuthorizationState(classification, decision.DeepClone() as JsonObject ?? new(), requestId);
        return PipeServer.Response(200, decision);
    }

    private async Task<JsonObject> RecordHookAsync(string kind, JsonObject payload, ClientIdentity client)
    {
        var sessionId = String(payload, "session_id");
        _sessions.TryGetValue(sessionId, out var session);
        await enterprise.AuditAsync(
            kind,
            $"Recorded Claude hook event {kind}",
            new JsonObject
            {
                ["session_id"] = sessionId,
                ["trace_id"] = session?.TraceId,
                ["agent_run"] = session?.AgentRun,
                ["user"] = session?.User,
                ["device"] = session?.Device,
                ["agent"] = "claude-code",
                ["tool_name"] = String(payload, "tool_name"),
                ["tool_use_id"] = String(payload, "tool_use_id"),
                ["client"] = ClientDetails(client, kind)
            },
            kind == "PERMISSION_REQUEST" ? "warning" : "success");
        return PipeServer.Response(200, new JsonObject { ["ok"] = true });
    }

    private async Task<JsonObject> ExecuteResourceAsync(JsonObject payload, ClientIdentity client)
    {
        var sessionId = String(payload, "session_id");
        var operation = String(payload, "operation", "read");
        if (!_sessions.TryGetValue(sessionId, out var session)
            || !_authorizations.TryGetValue(sessionId, out var authorization))
        {
            await enterprise.AuditAsync(
                "NO_GRANT_DENIED",
                "Denied resource execution without a registered authorized session",
                new JsonObject { ["trace_id"] = session?.TraceId ?? "trc-" + Guid.NewGuid().ToString("N"), ["request_id"] = "req-" + Guid.NewGuid().ToString("N"), ["session_id"] = sessionId, ["agent_run"] = session?.AgentRun, ["user"] = session?.User, ["device"] = session?.Device, ["agent"] = "bap-resource-client", ["operation"] = operation, ["decision"] = "DENY", ["decision_reason"] = "No authorized session-held grant", ["outcome"] = "DENIED" },
                "error");
            return PipeServer.Response(403, new JsonObject { ["ok"] = false, ["error"] = "No authorized session-held grant" });
        }
        if (!string.Equals(operation, authorization.Classification.Operation, StringComparison.Ordinal))
        {
            await enterprise.AuditAsync(
                "EXECUTION_DENIED",
                "Runtime operation differs from the authorized action",
                new JsonObject { ["trace_id"] = session.TraceId, ["request_id"] = authorization.RequestId, ["decision_id"] = String(authorization.BapDecision, "decision_id"), ["session_id"] = sessionId, ["agent_run"] = session.AgentRun, ["user"] = session.User, ["device"] = session.Device, ["agent"] = "bap-resource-client", ["action"] = authorization.Classification.Action, ["resource"] = authorization.Classification.Resource, ["operation"] = operation, ["decision"] = "DENY", ["decision_reason"] = "Operation differs from authorized action", ["outcome"] = "DENIED" },
                "error");
            return PipeServer.Response(403, new JsonObject { ["ok"] = false, ["error"] = "Operation differs from authorized action" });
        }

        var decision = String(authorization.BapDecision, "decision");
        if (decision == "REQUIRE_APPROVAL")
        {
            var (approvalStatus, approval) = await enterprise.BapAsync("approve", new JsonObject
            {
                ["request_id"] = String(authorization.BapDecision, "approval_request_id"),
                ["approver"] = session.User
            });
            if (approvalStatus != 200 || approval["grant"] is not JsonObject approvedGrant)
            {
                await enterprise.AuditAsync("EXECUTION_DENIED", "Approval activation failed", new JsonObject { ["trace_id"] = session.TraceId, ["request_id"] = authorization.RequestId, ["decision_id"] = String(authorization.BapDecision, "decision_id"), ["session_id"] = sessionId, ["agent_run"] = session.AgentRun, ["user"] = session.User, ["device"] = session.Device, ["agent"] = "bap-resource-client", ["action"] = authorization.Classification.Action, ["resource"] = authorization.Classification.Resource, ["approval_request_id"] = String(authorization.BapDecision, "approval_request_id"), ["decision"] = "DENY", ["decision_reason"] = "Approval activation failed", ["http_status"] = approvalStatus, ["outcome"] = "DENIED" }, "error");
                return PipeServer.Response(403, new JsonObject { ["ok"] = false, ["error"] = "Approval activation failed" });
            }
            authorization.BapDecision["decision"] = "ALLOW";
            authorization.BapDecision["decision_id"] = approval["decision_id"]?.DeepClone();
            authorization.BapDecision["grant"] = approvedGrant.DeepClone();
        }
        if (authorization.BapDecision["grant"] is not JsonObject grant)
        {
            await enterprise.AuditAsync("EXECUTION_DENIED", "BAP did not issue a grant", new JsonObject { ["trace_id"] = session.TraceId, ["request_id"] = authorization.RequestId, ["decision_id"] = String(authorization.BapDecision, "decision_id"), ["session_id"] = sessionId, ["agent_run"] = session.AgentRun, ["user"] = session.User, ["device"] = session.Device, ["agent"] = "bap-resource-client", ["action"] = authorization.Classification.Action, ["resource"] = authorization.Classification.Resource, ["decision"] = "DENY", ["decision_reason"] = "BAP did not issue a grant", ["outcome"] = "DENIED" }, "error");
            return PipeServer.Response(403, new JsonObject { ["ok"] = false, ["error"] = "BAP did not issue a grant" });
        }

        var resourceKey = String(payload, "key", "customer-123");
        var (status, result) = await enterprise.ResourceAsync(new JsonObject
        {
            ["token"] = String(grant, "token"),
            ["trace_id"] = session.TraceId,
            ["request_id"] = authorization.RequestId,
            ["decision_id"] = String(authorization.BapDecision, "decision_id", String(grant, "decision_id")),
            ["action"] = authorization.Classification.Action,
            ["resource"] = authorization.Classification.Resource,
            ["agent_run"] = session.AgentRun,
            ["operation"] = operation,
            ["key"] = resourceKey,
            ["value"] = payload["value"]?.DeepClone()
        });
        await enterprise.AuditAsync(
            status == 200 ? "RESOURCE_RESULT_RETURNED" : "RESOURCE_RESULT_DENIED",
            $"Resource gateway returned HTTP {status} to the signed resource client",
            new JsonObject
            {
                ["session_id"] = sessionId,
                ["trace_id"] = session.TraceId,
                ["request_id"] = authorization.RequestId,
                ["decision_id"] = String(authorization.BapDecision, "decision_id", String(grant, "decision_id")),
                ["agent_run"] = session.AgentRun,
                ["user"] = session.User,
                ["device"] = session.Device,
                ["agent"] = "bap-resource-client",
                ["action"] = authorization.Classification.Action,
                ["resource"] = authorization.Classification.Resource,
                ["resource_key"] = resourceKey,
                ["grant_id"] = String(grant, "grant_id"),
                ["execution_id"] = String(result, "execution_id"),
                ["http_status"] = status,
                ["outcome"] = status == 200 ? "SUCCEEDED" : "DENIED",
                ["client"] = ClientDetails(client, "/resource/execute")
            },
            status == 200 ? "success" : "error",
            required: false);
        return PipeServer.Response(status, result);
    }

    private async Task<JsonObject> EndSessionAsync(JsonObject payload, ClientIdentity client)
    {
        var sessionId = String(payload, "session_id");
        if (_sessions.TryRemove(sessionId, out var session))
        {
            _authorizations.TryRemove(sessionId, out _);
            await enterprise.BapAsync("revoke-session", new JsonObject { ["trace_id"] = session.TraceId, ["session_id"] = sessionId, ["agent_run"] = session.AgentRun, ["user"] = session.User, ["device"] = session.Device, ["agent"] = "claude-code" });
            await enterprise.AuditAsync(
                "SESSION_ENDED",
                $"Closed {session.AgentRun} and revoked its grants",
                SessionDetails(session, client),
                "warning");
        }
        else
        {
            await enterprise.AuditAsync("SESSION_END_IGNORED", "No registered session existed to close", new JsonObject { ["request_id"] = "req-" + Guid.NewGuid().ToString("N"), ["session_id"] = sessionId, ["outcome"] = "NO_CHANGE", ["client"] = ClientDetails(client, "/session/end") }, "warning");
        }
        return PipeServer.Response(200, new JsonObject { ["ok"] = true });
    }

    private static Classification Classify(string toolName, JsonObject input)
    {
        if (toolName is not ("Bash" or "PowerShell"))
        {
            return new Classification("LOCAL", "", "", "", $"Local Claude tool {toolName}");
        }
        var command = String(input, "command");
        var normalized = command.Replace('\\', '/').ToLowerInvariant();
        if (normalized.Contains("direct_db_client.py", StringComparison.Ordinal)
            || normalized.Contains("direct_resource_client", StringComparison.Ordinal))
        {
            return new Classification("BYPASS", "", "", "", "attempted direct protected-resource access");
        }
        if (!normalized.Contains("db_client.py", StringComparison.Ordinal)
            && !normalized.Contains("bap_resource_client", StringComparison.Ordinal))
        {
            return new Classification("LOCAL", "", "", "", command.Length > 160 ? command[..160] : command);
        }
        var operation = new[] { "delete", "write", "prod-read", "read" }
            .FirstOrDefault(candidate => $" {normalized}".Contains($" {candidate}", StringComparison.Ordinal)) ?? "read";
        var resource = operation == "prod-read" ? "prod-customer-db" : "dev-customer-db";
        var action = operation is "read" or "prod-read" ? "database.read"
            : operation == "write" ? "database.write" : "database.delete";
        var runtimeOperation = operation == "prod-read" ? "read" : operation;
        return new Classification("PROTECTED", action, resource, runtimeOperation, $"{action} on {resource}");
    }

    private static JsonObject ClientDetails(ClientIdentity client, string path) => new()
    {
        ["request_path"] = path,
        ["client_process_id"] = client.ProcessId,
        ["client_executable"] = client.ExecutablePath,
        ["client_signer_subject"] = client.SignerSubject,
        ["client_signer_thumbprint"] = client.SignerThumbprint,
        ["client_signed"] = client.IsSigned
    };

    private static JsonObject SessionDetails(SessionState session, ClientIdentity client) => new()
    {
        ["session_id"] = session.SessionId,
        ["trace_id"] = session.TraceId,
        ["agent_run"] = session.AgentRun,
        ["agent"] = "claude-code",
        ["user"] = session.User,
        ["device"] = session.Device,
        ["cwd"] = session.Cwd,
        ["task"] = session.Task,
        ["client"] = ClientDetails(client, "session")
    };

    private static string String(JsonObject value, string key, string fallback = "")
    {
        try { return value[key]?.GetValue<string>() ?? fallback; }
        catch (InvalidOperationException) { return fallback; }
    }
}

internal sealed class SessionState(
    string sessionId,
    string agentRun,
    string traceId,
    string user,
    string device,
    string cwd,
    string task)
{
    public string SessionId { get; } = sessionId;
    public string AgentRun { get; } = agentRun;
    public string TraceId { get; } = traceId;
    public string User { get; } = user;
    public string Device { get; } = device;
    public string Cwd { get; } = cwd;
    public string Task { get; set; } = task;
}

internal sealed record Classification(string Category, string Action, string Resource, string Operation, string Summary);
internal sealed record AuthorizationState(Classification Classification, JsonObject BapDecision, string RequestId);
