namespace Company.Bap.ConnectorService;

internal sealed record ConnectorOptions(
    string PipeName,
    Uri BapBaseUri,
    Uri ResourceGatewayBaseUri,
    string ClientPfxPath,
    string ClientPfxPassword,
    string CaCertificatePath,
    bool RequireSignedClients)
{
    public static ConnectorOptions Parse(string[] args)
    {
        var values = new Dictionary<string, string>(StringComparer.OrdinalIgnoreCase);
        for (var index = 0; index < args.Length; index++)
        {
            if (!args[index].StartsWith("--", StringComparison.Ordinal) || index + 1 >= args.Length)
            {
                throw new ArgumentException($"Invalid option near {args[index]}");
            }
            values[args[index][2..]] = args[++index];
        }

        string Required(string key) => values.TryGetValue(key, out var value)
            ? value
            : throw new ArgumentException($"Missing --{key}");

        return new ConnectorOptions(
            values.GetValueOrDefault("pipe", "Company.BAP.Connector.v1"),
            new Uri(values.GetValueOrDefault("bap-url", "https://127.0.0.1:11443/")),
            new Uri(values.GetValueOrDefault("resource-url", "https://127.0.0.1:11444/")),
            Path.GetFullPath(Required("client-pfx")),
            Required("pfx-password"),
            Path.GetFullPath(Required("ca-cert")),
            bool.TryParse(values.GetValueOrDefault("require-signed-clients", "false"), out var required) && required);
    }
}
