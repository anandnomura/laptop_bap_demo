$ErrorActionPreference = 'Stop'
$demoRoot = Split-Path -Parent (Split-Path -Parent $MyInvocation.MyCommand.Path)
$pfx = Join-Path $demoRoot 'runtime\pki\demo-code-signing.pfx'
$password = ConvertTo-SecureString 'demo-only-change-me' -AsPlainText -Force
$targets = @(
    (Join-Path $demoRoot 'claude_guard\publish\claude_guard.exe'),
    (Join-Path $demoRoot 'laptop_connector_service\publish\bap_connector_service.exe'),
    (Join-Path $demoRoot 'bap_resource_client\publish\bap_resource_client.exe')
)

foreach ($target in $targets) {
    if (-not (Test-Path -LiteralPath $target)) { throw "Missing binary: $target" }
}

$certificate = Import-PfxCertificate -FilePath $pfx -CertStoreLocation Cert:\CurrentUser\My -Password $password
try {
    foreach ($target in $targets) {
        $signature = Set-AuthenticodeSignature -LiteralPath $target -Certificate $certificate -HashAlgorithm SHA256
        if (-not $signature.SignerCertificate) { throw "Authenticode signing failed for $target" }
        Write-Host "Demo-signed: $target" -ForegroundColor Green
        Write-Host "  Subject: $($signature.SignerCertificate.Subject)"
        Write-Host "  Status:  $($signature.Status) (self-signed demo trust may report UnknownError)"
    }
} finally {
    Remove-Item -LiteralPath "Cert:\CurrentUser\My\$($certificate.Thumbprint)" -Force -ErrorAction SilentlyContinue
}

Write-Warning 'These signatures use a local demo certificate and have no trusted timestamp. They are not enterprise release signatures.'
