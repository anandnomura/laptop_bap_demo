using System.Buffers.Binary;
using System.Diagnostics;
using System.IO.Pipes;
using System.Runtime.InteropServices;
using System.Security.Cryptography.X509Certificates;
using System.Text;
using System.Text.Json.Nodes;
using Microsoft.Win32.SafeHandles;

namespace Company.Bap.ClaudeGuard;

internal sealed partial class ConnectorClient : IDisposable
{
#if LAB_BUILD
    internal const string EndpointDescription = "http://127.0.0.1:11022/ (lab HTTP)";
    private static readonly Uri ConnectorBaseUri = new("http://127.0.0.1:11022/");
    private readonly HttpClient _httpClient = CreateHttpClient();
#else
    internal const string EndpointDescription = @"\\.\pipe\Company.BAP.Connector.v1";
    private const string PipeName = "Company.BAP.Connector.v1";
#endif

    public async Task<ConnectorResponse> PostAsync(string relativePath, JsonObject payload)
    {
        DebugLog.Write($"POST /{relativePath.TrimStart('/')} session={SafeMetadata(payload, "session_id")} tool={SafeMetadata(payload, "tool_name")}");
#if LAB_BUILD
        using var content = new StringContent(payload.ToJsonString(), Encoding.UTF8, "application/json");
        using var response = await _httpClient.PostAsync(relativePath, content);
        var parsed = ParseObject(await response.Content.ReadAsStringAsync());
        DebugLog.Write($"connector_status={(int)response.StatusCode}");
        return new ConnectorResponse(response.StatusCode, parsed);
#else
        await using var pipe = new NamedPipeClientStream(
            ".",
            PipeName,
            PipeDirection.InOut,
            PipeOptions.Asynchronous | PipeOptions.WriteThrough);
        await pipe.ConnectAsync(2000);
        VerifyServerProcess(pipe.SafePipeHandle);
        await WriteFrameAsync(pipe, new JsonObject
        {
            ["path"] = "/" + relativePath.TrimStart('/'),
            ["payload"] = payload.DeepClone()
        });
        var response = await ReadFrameAsync(pipe);
        var status = response["status"]?.GetValue<int>() ?? 500;
        var body = response["body"] as JsonObject ?? new JsonObject { ["error"] = "Connector returned no response body" };
        DebugLog.Write($"connector_status={status}");
        return new ConnectorResponse((System.Net.HttpStatusCode)status, body);
#endif
    }

    public async Task<bool> CheckHealthAsync()
    {
        try
        {
#if LAB_BUILD
            using var response = await _httpClient.GetAsync("health");
            var ok = response.IsSuccessStatusCode;
#else
            var response = await PostAsync("health", new JsonObject());
            var ok = response.IsSuccess && response.Body["ok"]?.GetValue<bool>() == true;
#endif
            Console.WriteLine(ok
                ? $"ClaudeGuard can reach {EndpointDescription}"
                : $"ClaudeGuard health check failed for {EndpointDescription}");
            return ok;
        }
        catch (Exception exception)
        {
            Console.Error.WriteLine($"Connector health check failed: {exception.Message}");
            return false;
        }
    }

#if LAB_BUILD
    private static HttpClient CreateHttpClient()
    {
        var handler = new SocketsHttpHandler
        {
            AllowAutoRedirect = false,
            UseProxy = false,
            ConnectTimeout = TimeSpan.FromSeconds(2)
        };
        var client = new HttpClient(handler)
        {
            BaseAddress = ConnectorBaseUri,
            Timeout = TimeSpan.FromSeconds(5)
        };
        client.DefaultRequestHeaders.UserAgent.ParseAdd("Company-ClaudeGuard-Lab/0.1.0");
        return client;
    }
#endif

    private static JsonObject ParseObject(string value)
    {
        try { return JsonNode.Parse(value) as JsonObject ?? new JsonObject(); }
        catch (System.Text.Json.JsonException) { return new JsonObject { ["error"] = "Connector returned invalid JSON" }; }
    }

    private static string SafeMetadata(JsonObject payload, string key)
    {
        try
        {
            var value = payload[key]?.GetValue<string>();
            return string.IsNullOrEmpty(value) ? "-" : value[..Math.Min(value.Length, 80)];
        }
        catch (InvalidOperationException) { return "-"; }
    }

#if !LAB_BUILD
    private static async Task WriteFrameAsync(Stream stream, JsonObject message)
    {
        var body = Encoding.UTF8.GetBytes(message.ToJsonString());
        var length = new byte[4];
        BinaryPrimitives.WriteInt32LittleEndian(length, body.Length);
        await stream.WriteAsync(length);
        await stream.WriteAsync(body);
        await stream.FlushAsync();
    }

    private static async Task<JsonObject> ReadFrameAsync(Stream stream)
    {
        var lengthBytes = new byte[4];
        await stream.ReadExactlyAsync(lengthBytes);
        var length = BinaryPrimitives.ReadInt32LittleEndian(lengthBytes);
        if (length is <= 0 or > 1024 * 1024) throw new InvalidDataException("Invalid connector frame length");
        var body = new byte[length];
        await stream.ReadExactlyAsync(body);
        return JsonNode.Parse(body) as JsonObject ?? throw new InvalidDataException("Connector response is not a JSON object");
    }

    private static void VerifyServerProcess(SafePipeHandle pipeHandle)
    {
        if (!GetNamedPipeServerProcessId(pipeHandle, out var processId))
        {
            throw new InvalidOperationException("Cannot identify the named-pipe server process");
        }
        using var process = Process.GetProcessById(checked((int)processId));
        var path = process.MainModule?.FileName ?? throw new InvalidOperationException("Cannot resolve connector service executable");
        if (!string.Equals(Path.GetFileName(path), "bap_connector_service.exe", StringComparison.OrdinalIgnoreCase))
        {
            throw new InvalidOperationException("Named-pipe server is not the approved connector service executable");
        }
        try
        {
            using var signer = new X509Certificate2(X509Certificate.CreateFromSignedFile(path));
            if (!signer.Subject.Contains("Company BAP Demo Code Signing", StringComparison.OrdinalIgnoreCase))
            {
                throw new InvalidOperationException("Connector service signer is not approved");
            }
        }
        catch (System.Security.Cryptography.CryptographicException exception)
        {
            throw new InvalidOperationException("Connector service executable is not Authenticode signed", exception);
        }
    }

    [LibraryImport("kernel32.dll", SetLastError = true)]
    [return: MarshalAs(UnmanagedType.Bool)]
    private static partial bool GetNamedPipeServerProcessId(SafePipeHandle pipe, out uint serverProcessId);
#endif

    public void Dispose()
    {
#if LAB_BUILD
        _httpClient.Dispose();
#endif
    }
}

internal sealed record ConnectorResponse(System.Net.HttpStatusCode StatusCode, JsonObject Body)
{
    public bool IsSuccess => StatusCode == System.Net.HttpStatusCode.OK;
}
