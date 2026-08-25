using System.Buffers.Binary;
using System.Text;
using System.Text.Json.Nodes;

namespace Company.Bap.ConnectorService;

internal static class PipeProtocol
{
    private const int MaximumMessageBytes = 1024 * 1024;

    public static async Task<JsonObject> ReadAsync(Stream stream, CancellationToken cancellationToken)
    {
        var lengthBytes = new byte[4];
        await stream.ReadExactlyAsync(lengthBytes, cancellationToken);
        var length = BinaryPrimitives.ReadInt32LittleEndian(lengthBytes);
        if (length is <= 0 or > MaximumMessageBytes)
        {
            throw new InvalidDataException("Named-pipe message length is invalid.");
        }
        var body = new byte[length];
        await stream.ReadExactlyAsync(body, cancellationToken);
        return JsonNode.Parse(body) as JsonObject
            ?? throw new InvalidDataException("Named-pipe message must be a JSON object.");
    }

    public static async Task WriteAsync(Stream stream, JsonObject message, CancellationToken cancellationToken)
    {
        var body = Encoding.UTF8.GetBytes(message.ToJsonString());
        if (body.Length > MaximumMessageBytes)
        {
            throw new InvalidDataException("Named-pipe response exceeds the maximum size.");
        }
        var lengthBytes = new byte[4];
        BinaryPrimitives.WriteInt32LittleEndian(lengthBytes, body.Length);
        await stream.WriteAsync(lengthBytes, cancellationToken);
        await stream.WriteAsync(body, cancellationToken);
        await stream.FlushAsync(cancellationToken);
    }
}
