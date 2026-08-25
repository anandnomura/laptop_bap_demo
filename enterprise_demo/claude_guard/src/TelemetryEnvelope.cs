using System.Runtime.InteropServices;
using System.Text.Json.Nodes;

namespace Company.Bap.ClaudeGuard;

internal static class TelemetryEnvelope
{
    public static void AddTo(JsonObject hookEvent, string action)
    {
        // Client metadata improves diagnostics and correlation. It is self-reported
        // and must not be treated as proof of binary integrity by the connector.
        hookEvent["client_metadata"] = new JsonObject
        {
            ["schema_version"] = "1.0",
            ["event_id"] = Guid.NewGuid().ToString("D"),
            ["emitted_at"] = DateTimeOffset.UtcNow.ToString("O"),
            ["product"] = "Company ClaudeGuard",
            ["version"] = "0.1.0",
            ["build_flavor"] = BuildInfo.IsLabBuild ? "lab" : "production",
            ["hook_action"] = action,
            ["host"] = Environment.MachineName,
            ["user"] = Environment.UserName,
            ["process_id"] = Environment.ProcessId,
            ["process_architecture"] = RuntimeInformation.ProcessArchitecture.ToString().ToLowerInvariant(),
            ["runtime"] = RuntimeInformation.FrameworkDescription,
            ["executable_path"] = Environment.ProcessPath
        };
    }
}
