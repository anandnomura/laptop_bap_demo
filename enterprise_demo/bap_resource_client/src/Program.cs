using System.Buffers.Binary;
using System.Diagnostics;
using System.IO.Pipes;
using System.Runtime.InteropServices;
using System.Security.Cryptography.X509Certificates;
using System.Text;
using System.Text.Json.Nodes;
using Microsoft.Win32.SafeHandles;

namespace Company.Bap.ResourceClient;

internal static partial class Program
{
    private const string PipeName = "Company.BAP.Connector.v1";

    public static async Task<int> Main(string[] args)
    {
        try
        {
            var request = Parse(args);
            await using var pipe = new NamedPipeClientStream(
                ".", PipeName, PipeDirection.InOut, PipeOptions.Asynchronous | PipeOptions.WriteThrough);
            await pipe.ConnectAsync(2000);
            VerifyServer(pipe.SafePipeHandle);
            await WriteAsync(pipe, new JsonObject { ["path"] = "/resource/execute", ["payload"] = request });
            var response = await ReadAsync(pipe);
            var status = response["status"]?.GetValue<int>() ?? 500;
            Console.WriteLine((response["body"] as JsonObject ?? new JsonObject()).ToJsonString(new() { WriteIndented = true }));
            return status == 200 ? 0 : 1;
        }
        catch (Exception exception)
        {
            Console.Error.WriteLine($"BAP resource client failed: {exception.Message}");
            return 2;
        }
    }

    private static JsonObject Parse(string[] args)
    {
        if (args.Length < 2 || args[0] is not ("read" or "write" or "delete" or "prod-read"))
        {
            throw new ArgumentException("Usage: bap_resource_client <read|write|delete|prod-read> <key> [field=value ...] --bap-session <id>");
        }
        var sessionIndex = Array.FindIndex(args, value => value == "--bap-session");
        if (sessionIndex < 0 || sessionIndex + 1 >= args.Length)
        {
            throw new ArgumentException("--bap-session is required and is injected by ClaudeGuard");
        }
        var operation = args[0] == "prod-read" ? "read" : args[0];
        var payload = new JsonObject
        {
            ["operation"] = operation,
            ["key"] = args[1],
            ["session_id"] = args[sessionIndex + 1]
        };
        if (operation == "write")
        {
            var value = new JsonObject();
            foreach (var assignment in args.Skip(2).Take(Math.Max(0, sessionIndex - 2)))
            {
                var separator = assignment.IndexOf('=');
                if (separator <= 0) throw new ArgumentException($"Expected field=value, received {assignment}");
                value[assignment[..separator]] = assignment[(separator + 1)..];
            }
            payload["value"] = value;
        }
        return payload;
    }

    private static async Task WriteAsync(Stream stream, JsonObject value)
    {
        var body = Encoding.UTF8.GetBytes(value.ToJsonString());
        var length = new byte[4];
        BinaryPrimitives.WriteInt32LittleEndian(length, body.Length);
        await stream.WriteAsync(length);
        await stream.WriteAsync(body);
        await stream.FlushAsync();
    }

    private static async Task<JsonObject> ReadAsync(Stream stream)
    {
        var prefix = new byte[4];
        await stream.ReadExactlyAsync(prefix);
        var length = BinaryPrimitives.ReadInt32LittleEndian(prefix);
        if (length is <= 0 or > 1024 * 1024) throw new InvalidDataException("Invalid connector response length");
        var body = new byte[length];
        await stream.ReadExactlyAsync(body);
        return JsonNode.Parse(body) as JsonObject ?? throw new InvalidDataException("Connector response is not JSON");
    }

    private static void VerifyServer(SafePipeHandle handle)
    {
        if (!GetNamedPipeServerProcessId(handle, out var processId))
            throw new InvalidOperationException("Cannot identify named-pipe server");
        using var process = Process.GetProcessById(checked((int)processId));
        var path = process.MainModule?.FileName ?? throw new InvalidOperationException("Cannot resolve connector executable");
        if (!string.Equals(Path.GetFileName(path), "bap_connector_service.exe", StringComparison.OrdinalIgnoreCase))
            throw new InvalidOperationException("Named-pipe server executable is not approved");
        try
        {
            using var signer = new X509Certificate2(X509Certificate.CreateFromSignedFile(path));
            if (!signer.Subject.Contains("Company BAP Demo Code Signing", StringComparison.OrdinalIgnoreCase))
                throw new InvalidOperationException("Connector service signer is not approved");
        }
        catch (System.Security.Cryptography.CryptographicException exception)
        {
            throw new InvalidOperationException("Connector service is not signed", exception);
        }
    }

    [LibraryImport("kernel32.dll", SetLastError = true)]
    [return: MarshalAs(UnmanagedType.Bool)]
    private static partial bool GetNamedPipeServerProcessId(SafePipeHandle pipe, out uint serverProcessId);
}
