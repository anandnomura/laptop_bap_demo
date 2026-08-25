using System.Text.Json;
using System.Text.Json.Nodes;

namespace Company.Bap.ClaudeGuard;

internal static class Program
{
    private static readonly HashSet<string> SupportedActions =
    [
        "session-start",
        "capture-intent",
        "authorize",
        "permission-request",
        "post-tool",
        "session-end"
    ];

    public static async Task<int> Main(string[] args)
    {
        if (args.Length == 1 && args[0] == "--version")
        {
            Console.WriteLine(BuildInfo.Description);
            return 0;
        }

        if (args.Length == 1 && args[0] == "--health")
        {
            using var healthClient = new ConnectorClient();
            return await healthClient.CheckHealthAsync() ? 0 : 2;
        }

        if (!GuardOptions.TryParse(args, SupportedActions, out var options, out var optionError))
        {
            Console.Error.WriteLine(optionError);
            return 2;
        }

        var action = options!.Action;
        DebugLog.Enabled = options.Debug;
        if (BuildInfo.IsLabBuild)
        {
            Console.Error.WriteLine("WARNING: ClaudeGuard LAB BUILD. Never deploy or allowlist this executable on a controlled laptop.");
        }

        DebugLog.Write($"action={action} connector={ConnectorClient.EndpointDescription} bypass={options.Bypass}");
        try
        {
            var input = await Console.In.ReadToEndAsync();
            var eventObject = JsonNode.Parse(string.IsNullOrWhiteSpace(input) ? "{}" : input) as JsonObject
                ?? throw new JsonException("Hook input must be a JSON object.");
            TelemetryEnvelope.AddTo(eventObject, action);

            using var connector = new ConnectorClient();
            var processor = new HookProcessor(connector, options);
            return await processor.HandleAsync(action, eventObject);
        }
        catch (Exception exception) when (exception is JsonException or InvalidOperationException)
        {
            return FailSafely(action, $"Invalid hook input: {exception.Message}");
        }
        catch (Exception exception)
        {
            return FailSafely(action, $"ClaudeGuard failed: {exception.Message}");
        }
    }

    private static int FailSafely(string action, string reason)
    {
        if (action == "authorize")
        {
            HookOutput.WriteAuthorization("deny", reason);
            return 0;
        }

        Console.Error.WriteLine(reason);
        return 2;
    }
}

internal static class BuildInfo
{
#if LAB_BUILD
    public static bool IsLabBuild => true;
    public const string Description = "claude_guard_lab 0.1.0 (LAB BUILD; bypass capability compiled in)";
#else
    public static bool IsLabBuild => false;
    public const string Description = "claude_guard 0.1.0 (production build; no bypass capability)";
#endif
}

internal sealed record GuardOptions(string Action, bool Debug, bool Bypass)
{
    public static bool TryParse(
        string[] args,
        HashSet<string> supportedActions,
        out GuardOptions? options,
        out string error)
    {
        options = null;
        error = "Usage: claude_guard <action>";

        var action = args.FirstOrDefault(argument => !argument.StartsWith("--", StringComparison.Ordinal));
        if (action is null || !supportedActions.Contains(action))
        {
            error = "Usage: claude_guard <session-start|capture-intent|authorize|permission-request|post-tool|session-end>";
            return false;
        }

        var flags = args.Where(argument => argument.StartsWith("--", StringComparison.Ordinal)).ToArray();
        if (args.Length != flags.Length + 1)
        {
            error = "Only one hook action may be supplied.";
            return false;
        }

#if LAB_BUILD
        var unknown = flags.Where(flag => flag is not "--debug" and not "--lab-bypass").ToArray();
        if (unknown.Length != 0)
        {
            error = $"Unknown lab option: {unknown[0]}";
            return false;
        }

        var debug = flags.Contains("--debug", StringComparer.Ordinal);
        var bypass = flags.Contains("--lab-bypass", StringComparer.Ordinal);
        if (bypass && action != "authorize")
        {
            error = "--lab-bypass is valid only with the authorize action.";
            return false;
        }

        options = new GuardOptions(action, debug, bypass);
        return true;
#else
        if (flags.Length != 0)
        {
            error = "This production build does not support debug or bypass flags.";
            return false;
        }

        options = new GuardOptions(action, Debug: false, Bypass: false);
        return true;
#endif
    }
}

internal static class DebugLog
{
    public static bool Enabled { get; set; }

    public static void Write(string message)
    {
        if (Enabled)
        {
            // stderr is intentional: Claude hook stdout must contain only its JSON decision.
            Console.Error.WriteLine($"[ClaudeGuard debug] {message}");
        }
    }
}
