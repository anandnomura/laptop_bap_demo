namespace Company.Bap.ConnectorService;

internal static class Program
{
    public static async Task<int> Main(string[] args)
    {
        try
        {
            var options = ConnectorOptions.Parse(args);
            using var enterprise = new EnterpriseClient(options);
            var runtime = new ConnectorRuntime(enterprise);
            var server = new PipeServer(options, runtime);
            Console.WriteLine($"BAP Connector Service 0.1.0");
            Console.WriteLine($@"Named pipe: \\.\pipe\{options.PipeName}");
            Console.WriteLine($"Central BAP: {options.BapBaseUri}");
            Console.WriteLine($"Resource gateway: {options.ResourceGatewayBaseUri}");
            Console.WriteLine($"Signed client enforcement: {options.RequireSignedClients}");
            // Startup must remain available through a temporary network outage. The
            // durable outbox records and replays this event before the next operation.
            await enterprise.AuditAsync("CONNECTOR_SERVICE_READY", "Laptop connector named-pipe service is ready", new(), required: false);
            await server.RunAsync();
            return 0;
        }
        catch (Exception exception)
        {
            Console.Error.WriteLine($"Connector service failed: {exception}");
            return 1;
        }
    }
}
