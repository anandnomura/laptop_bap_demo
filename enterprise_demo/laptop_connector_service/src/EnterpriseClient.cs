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

    public async Task AuditAsync(string kind, string message, JsonObject details, string level = "info")
    {
        try
        {
            await BapAsync("audit", new JsonObject
            {
                ["source"] = "LAPTOP CONNECTOR",
                ["kind"] = kind,
                ["message"] = message,
                ["level"] = level,
                ["details"] = details
            });
        }
        catch (Exception exception)
        {
            Console.Error.WriteLine($"Central audit unavailable: {exception}");
        }
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
    }
}
