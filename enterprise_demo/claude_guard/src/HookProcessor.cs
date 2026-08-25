using System.Net;
using System.Text.RegularExpressions;
using System.Text.Json.Nodes;

namespace Company.Bap.ClaudeGuard;

internal sealed partial class HookProcessor(ConnectorClient connector, GuardOptions options)
{
    public async Task<int> HandleAsync(string action, JsonObject hookEvent)
    {
        return action switch
        {
            "session-start" => await SendSessionStartAsync(hookEvent),
            "capture-intent" => await SendRecordedEventAsync("intent", hookEvent),
            "authorize" => await AuthorizeAsync(hookEvent),
            "permission-request" => await SendRecordedEventAsync("hook/permission", hookEvent),
            "post-tool" => await SendRecordedEventAsync("hook/post-tool", hookEvent),
            "session-end" => await SendRecordedEventAsync("session/end", hookEvent),
            _ => 2
        };
    }

    private async Task<int> SendSessionStartAsync(JsonObject hookEvent)
    {
        hookEvent["user"] = Environment.UserName;
        return await SendRecordedEventAsync("session/start", hookEvent);
    }

    private async Task<int> SendRecordedEventAsync(string path, JsonObject hookEvent)
    {
        try
        {
            var response = await connector.PostAsync(path, hookEvent);
            if (response.IsSuccess)
            {
                return 0;
            }

            Console.Error.WriteLine($"BAP connector rejected {path}: HTTP {(int)response.StatusCode}.");
            return 2;
        }
        catch (Exception exception) when (exception is HttpRequestException or TaskCanceledException)
        {
            Console.Error.WriteLine($"BAP connector unavailable for {path}: {exception.Message}");
            return 2;
        }
    }

    private async Task<int> AuthorizeAsync(JsonObject hookEvent)
    {
        if (options.Bypass)
        {
            var unchangedInput = hookEvent["tool_input"]?.DeepClone() as JsonObject ?? new JsonObject();
            Console.Error.WriteLine("WARNING: LAB authorization bypass used; no BAP decision or grant was obtained.");
            HookOutput.WriteAuthorization(
                "allow",
                "LAB BYPASS: action allowed without a BAP decision. This is not a valid production grant.",
                unchangedInput);
            return 0;
        }

        ConnectorResponse response;
        try
        {
            response = await connector.PostAsync("hook/pre-tool", hookEvent);
        }
        catch (Exception exception) when (exception is HttpRequestException or TaskCanceledException)
        {
            HookOutput.WriteAuthorization("deny", $"Laptop BAP connector unavailable; fail closed: {exception.Message}");
            return 0;
        }

        if (!response.IsSuccess)
        {
            HookOutput.WriteAuthorization(
                "deny",
                $"Laptop BAP connector rejected the authorization request: HTTP {(int)response.StatusCode}");
            return 0;
        }

        var bapDecision = response.Body["decision"]?.GetValue<string>()?.ToUpperInvariant() ?? "DENY";
        var reason = response.Body["reason"]?.GetValue<string>() ?? "No BAP decision reason supplied.";
        var updatedInput = hookEvent["tool_input"]?.DeepClone() as JsonObject ?? new JsonObject();

        if (bapDecision == "ALLOW" && !TryBindProtectedDemoCommand(hookEvent, updatedInput, out var bindingError))
        {
            HookOutput.WriteAuthorization("deny", bindingError!);
            return 0;
        }

        switch (bapDecision)
        {
            case "ALLOW":
                HookOutput.WriteAuthorization("allow", reason, updatedInput);
                break;
            case "REQUIRE_APPROVAL":
                HookOutput.WriteAuthorization("ask", reason, updatedInput);
                break;
            default:
                HookOutput.WriteAuthorization("deny", reason);
                break;
        }

        return 0;
    }

    private static bool TryBindProtectedDemoCommand(
        JsonObject hookEvent,
        JsonObject updatedInput,
        out string? error)
    {
        error = null;
        var toolName = hookEvent["tool_name"]?.GetValue<string>();
        if (!string.Equals(toolName, "Bash", StringComparison.Ordinal)
            && !string.Equals(toolName, "PowerShell", StringComparison.Ordinal))
        {
            return true;
        }

        var command = updatedInput["command"]?.GetValue<string>() ?? string.Empty;
        var isProtectedClient = command.Contains("db_client.py", StringComparison.OrdinalIgnoreCase)
            || command.Contains("bap_resource_client", StringComparison.OrdinalIgnoreCase);
        if (!isProtectedClient
            || command.Contains("direct_db_client.py", StringComparison.OrdinalIgnoreCase)
            || command.Contains("direct_resource_client", StringComparison.OrdinalIgnoreCase)
            || command.Contains("--bap-session", StringComparison.Ordinal))
        {
            return true;
        }

        var sessionId = hookEvent["session_id"]?.GetValue<string>() ?? string.Empty;
        if (!SafeSessionId().IsMatch(sessionId))
        {
            error = "Cannot bind the protected command because the Claude session identifier is missing or invalid.";
            return false;
        }

        updatedInput["command"] = $"{command} --bap-session {sessionId}";
        return true;
    }

    [GeneratedRegex("^[A-Za-z0-9._:-]{1,200}$", RegexOptions.CultureInvariant)]
    private static partial Regex SafeSessionId();
}
