using System.Diagnostics;
using System.Runtime.InteropServices;
using System.Security.Cryptography.X509Certificates;
using Microsoft.Win32.SafeHandles;

namespace Company.Bap.ConnectorService;

internal static partial class ClientProcessInspector
{
    public static ClientIdentity Inspect(SafePipeHandle pipeHandle)
    {
        if (!GetNamedPipeClientProcessId(pipeHandle, out var processId))
        {
            throw new InvalidOperationException("Cannot identify named-pipe client process.");
        }
        using var process = Process.GetProcessById(checked((int)processId));
        var path = process.MainModule?.FileName
            ?? throw new InvalidOperationException("Cannot resolve named-pipe client executable path.");
        var signature = TryReadSignature(path);
        return new ClientIdentity((int)processId, Path.GetFullPath(path), signature.Subject, signature.Thumbprint);
    }

    private static (string? Subject, string? Thumbprint) TryReadSignature(string path)
    {
        try
        {
            using var certificate = new X509Certificate2(X509Certificate.CreateFromSignedFile(path));
            return (certificate.Subject, certificate.Thumbprint);
        }
        catch (System.Security.Cryptography.CryptographicException)
        {
            return (null, null);
        }
    }

    [LibraryImport("kernel32.dll", SetLastError = true)]
    [return: MarshalAs(UnmanagedType.Bool)]
    private static partial bool GetNamedPipeClientProcessId(SafePipeHandle pipe, out uint clientProcessId);
}

internal sealed record ClientIdentity(int ProcessId, string ExecutablePath, string? SignerSubject, string? SignerThumbprint)
{
    public string ExecutableName => Path.GetFileName(ExecutablePath);
    public bool IsSigned => !string.IsNullOrWhiteSpace(SignerThumbprint);
}
