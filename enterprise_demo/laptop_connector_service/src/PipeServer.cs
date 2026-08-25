using System.IO.Pipes;
using System.Text.Json.Nodes;

namespace Company.Bap.ConnectorService;

internal sealed class PipeServer(ConnectorOptions options, ConnectorRuntime runtime)
{
    public async Task RunAsync(CancellationToken cancellationToken = default)
    {
        while (!cancellationToken.IsCancellationRequested)
        {
            var pipe = new NamedPipeServerStream(
                options.PipeName,
                PipeDirection.InOut,
                NamedPipeServerStream.MaxAllowedServerInstances,
                PipeTransmissionMode.Byte,
                PipeOptions.Asynchronous | PipeOptions.WriteThrough);
            await pipe.WaitForConnectionAsync(cancellationToken);
            _ = HandleClientAsync(pipe, cancellationToken);
        }
    }

    private async Task HandleClientAsync(NamedPipeServerStream pipe, CancellationToken cancellationToken)
    {
        await using (pipe)
        {
            ClientIdentity? identity = null;
            var path = string.Empty;
            try
            {
                identity = ClientProcessInspector.Inspect(pipe.SafePipeHandle);
                var request = await PipeProtocol.ReadAsync(pipe, cancellationToken);
                path = request["path"]?.GetValue<string>() ?? string.Empty;
                var response = await AuthorizeClientAndDispatchAsync(identity, request);
                await PipeProtocol.WriteAsync(pipe, response, cancellationToken);
            }
            catch (Exception exception)
            {
                try { await runtime.RecordPipeFailureAsync(identity, path, exception); } catch { }
                var response = Response(500, new JsonObject { ["error"] = $"Connector pipe failure: {exception.Message}" });
                try { await PipeProtocol.WriteAsync(pipe, response, cancellationToken); } catch { }
            }
        }
    }

    private async Task<JsonObject> AuthorizeClientAndDispatchAsync(ClientIdentity identity, JsonObject request)
    {
        var path = request["path"]?.GetValue<string>() ?? string.Empty;
        var expectedExecutable = path == "/resource/execute"
            ? "bap_resource_client.exe"
            : "claude_guard.exe";
        if (!string.Equals(identity.ExecutableName, expectedExecutable, StringComparison.OrdinalIgnoreCase))
        {
            await runtime.RecordRejectedClientAsync(identity, path, "Unexpected executable name");
            return Response(403, new JsonObject { ["error"] = "Named-pipe caller is not an approved BAP client" });
        }
        if (options.RequireSignedClients
            && (!identity.IsSigned
                || identity.SignerSubject?.Contains("Company BAP Demo Code Signing", StringComparison.OrdinalIgnoreCase) != true))
        {
            await runtime.RecordRejectedClientAsync(identity, path, "Missing or unapproved client signature");
            return Response(403, new JsonObject { ["error"] = "Named-pipe client signature is missing or unapproved" });
        }
        return await runtime.DispatchAsync(path, request["payload"] as JsonObject ?? new JsonObject(), identity);
    }

    internal static JsonObject Response(int status, JsonObject body) => new()
    {
        ["status"] = status,
        ["body"] = body
    };
}
