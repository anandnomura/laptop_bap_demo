using System.Text.Json;
using System.Text.Json.Nodes;

namespace Company.Bap.ClaudeGuard;

internal static class HookOutput
{
    private static readonly JsonSerializerOptions OutputOptions = new()
    {
        WriteIndented = false
    };

    public static void WriteAuthorization(string decision, string reason, JsonObject? updatedInput = null)
    {
        var specificOutput = new JsonObject
        {
            ["hookEventName"] = "PreToolUse",
            ["permissionDecision"] = decision,
            ["permissionDecisionReason"] = reason
        };

        if (updatedInput is not null)
        {
            specificOutput["updatedInput"] = updatedInput;
        }

        var output = new JsonObject
        {
            ["hookSpecificOutput"] = specificOutput
        };
        Console.WriteLine(output.ToJsonString(OutputOptions));
    }
}
