using System.Net.Security;
using System.Security.Cryptography.X509Certificates;
using System.Text;
using System.Text.Json.Nodes;

namespace Company.Bap.ConnectorService;

internal sealed class EnterpriseClient : IDisposable
{
    private readonly ConnectorOptions _options;
    private readonly HttpClient _bap;
    private readonly HttpClient _resource;
    private readonly SemaphoreSlim _auditLock = new(1, 1);

    public EnterpriseClient(ConnectorOptions options)
    {
        _options = options;
        _bap = CreateClient(options.BapBaseUri);
        _resource = CreateClient(options.ResourceGatewayBaseUri);
    }

    private HttpClient CreateClient(Uri baseAddress)
    {
        var clientCertificate = new X509Certificate2(
            _options.ClientPfxPath,
            _options.ClientPfxPassword,
            X509KeyStorageFlags.UserKeySet | X509KeyStorageFlags.PersistKeySet);
        var trustedRoot = new X509Certificate2(_options.CaCertificatePath);
        var handler = new HttpClientHandler();
        handler.ClientCertificates.Add(clientCertificate);
        handler.ServerCertificateCustomValidationCallback = (_, certificate, chain, errors) =>
        {
            if (certificate is null || chain is null || errors.HasFlag(SslPolicyErrors.RemoteCertificateNameMismatch))
            {
                return false;
            }
            chain.ChainPolicy.TrustMode = X509ChainTrustMode.CustomRootTrust;
            chain.ChainPolicy.CustomTrustStore.Add(trustedRoot);
            chain.ChainPolicy.RevocationMode = X509RevocationMode.NoCheck; // Demo PKI has no CRL/OCSP.
            return chain.Build(new X509Certificate2(certificate));
        };
        return new HttpClient(handler) { BaseAddress = baseAddress, Timeout = TimeSpan.FromSeconds(5) };
    }

    public Task<(int Status, JsonObject Body)> BapAsync(string path, JsonObject payload) => PostAsync(_bap, path, payload);
    public Task<(int Status, JsonObject Body)> ResourceAsync(JsonObject payload) => PostAsync(_resource, "execute", payload);

    public async Task AuditAsync(string kind, string message, JsonObject details, string level = "info", bool required = true)
    {
        var envelope = new JsonObject
        {
            ["source"] = "LAPTOP CONNECTOR",
            ["kind"] = kind,
            ["message"] = message,
            ["level"] = level,
            ["details"] = details.DeepClone()
        };
        await _auditLock.WaitAsync();
        try
        {
            await FlushAuditOutboxUnsafeAsync();
            Exception? lastError = null;
            for (var attempt = 1; attempt <= 3; attempt++)
            {
                try
                {
                    var (status, _) = await BapAsync("audit", envelope);
                    if (status == 200) return;
                    lastError = new HttpRequestException($"Central audit returned HTTP {status}");
                }
                catch (Exception exception) when (exception is HttpRequestException or TaskCanceledException)
                {
                    lastError = exception;
                }
                await Task.Delay(TimeSpan.FromMilliseconds(100 * attempt));
            }
            AppendAuditOutbox(envelope);
            if (required)
            {
                throw new HttpRequestException("Central audit unavailable; event was durably queued and the protected operation failed closed", lastError);
            }
            Console.Error.WriteLine("Central audit unavailable after resource execution; event durably queued for replay.");
        }
        finally
        {
            _auditLock.Release();
        }
    }

    private async Task FlushAuditOutboxUnsafeAsync()
    {
        if (!File.Exists(_options.AuditOutboxPath)) return;
        var lines = await File.ReadAllLinesAsync(_options.AuditOutboxPath);
        if (lines.Length == 0) return;
        var remaining = new List<string>();
        for (var index = 0; index < lines.Length; index++)
        {
            try
            {
                var eventEnvelope = JsonNode.Parse(lines[index]) as JsonObject
                    ?? throw new InvalidDataException("Invalid audit outbox event");
                var (status, _) = await BapAsync("audit", eventEnvelope);
                if (status != 200) throw new HttpRequestException($"Central audit returned HTTP {status}");
            }
            catch
            {
                remaining.AddRange(lines[index..]);
                break;
            }
        }
        var temporary = _options.AuditOutboxPath + ".tmp";
        Directory.CreateDirectory(Path.GetDirectoryName(_options.AuditOutboxPath)!);
        await File.WriteAllLinesAsync(temporary, remaining);
        File.Move(temporary, _options.AuditOutboxPath, true);
    }

    private void AppendAuditOutbox(JsonObject envelope)
    {
        Directory.CreateDirectory(Path.GetDirectoryName(_options.AuditOutboxPath)!);
        using var stream = new FileStream(_options.AuditOutboxPath, FileMode.Append, FileAccess.Write, FileShare.Read, 4096, FileOptions.WriteThrough);
        using var writer = new StreamWriter(stream, new UTF8Encoding(false), leaveOpen: true);
        writer.WriteLine(envelope.ToJsonString());
        writer.Flush();
        stream.Flush(true);
    }

    private static async Task<(int Status, JsonObject Body)> PostAsync(HttpClient client, string path, JsonObject payload)
    {
        using var content = new StringContent(payload.ToJsonString(), Encoding.UTF8, "application/json");
        using var response = await client.PostAsync(path, content);
        var text = await response.Content.ReadAsStringAsync();
        JsonObject body;
        try { body = JsonNode.Parse(text) as JsonObject ?? new JsonObject(); }
        catch (System.Text.Json.JsonException) { body = new JsonObject { ["error"] = "Enterprise service returned invalid JSON" }; }
        return ((int)response.StatusCode, body);
    }

    public void Dispose()
    {
        _bap.Dispose();
        _resource.Dispose();
        _auditLock.Dispose();
    }
}
