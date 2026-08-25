param([switch]$RegeneratePki)

$ErrorActionPreference = 'Stop'
& (Join-Path $PSScriptRoot 'install_cedar_cli.ps1')
$demoRoot = Split-Path -Parent (Split-Path -Parent $MyInvocation.MyCommand.Path)
$repoRoot = Split-Path -Parent $demoRoot
$temporarySdk = Join-Path $env:TEMP 'claude-guard-dotnet-sdk\dotnet.exe'
$dotnet = (Get-Command dotnet -ErrorAction SilentlyContinue).Source

if (-not $dotnet -or -not (& $dotnet --list-sdks)) {
    if (Test-Path -LiteralPath $temporarySdk) {
        $dotnet = $temporarySdk
    } else {
        throw '.NET 8 SDK is required. Install it from https://dotnet.microsoft.com/download/dotnet/8.0'
    }
}

$pkiMarker = Join-Path $demoRoot 'runtime\pki\demo-ca.cert.pem'
if ($RegeneratePki -or -not (Test-Path -LiteralPath $pkiMarker)) {
    & py -3 (Join-Path $demoRoot 'demo_pki\generate_demo_pki.py')
    if ($LASTEXITCODE -ne 0) { throw 'Demo PKI generation failed.' }
}

$projects = @(
    @{
        Project = Join-Path $demoRoot 'claude_guard\src\ClaudeGuard.csproj'
        Output = Join-Path $demoRoot 'claude_guard\publish'
    },
    @{
        Project = Join-Path $demoRoot 'laptop_connector_service\src\BapConnectorService.csproj'
        Output = Join-Path $demoRoot 'laptop_connector_service\publish'
    },
    @{
        Project = Join-Path $demoRoot 'bap_resource_client\src\BapResourceClient.csproj'
        Output = Join-Path $demoRoot 'bap_resource_client\publish'
    }
)

foreach ($item in $projects) {
    & $dotnet publish $item.Project `
        --configuration Release `
        --runtime win-x64 `
        --self-contained false `
        -p:PublishSingleFile=true `
        -p:DebugType=None `
        -p:DebugSymbols=false `
        --output $item.Output
    if ($LASTEXITCODE -ne 0) { throw "Build failed: $($item.Project)" }
}

& (Join-Path $demoRoot 'demo_pki\sign-demo-binaries.ps1')
if ($LASTEXITCODE -ne 0) { throw 'Demo Authenticode signing failed.' }

Write-Host 'Enterprise demo binaries built and demo-signed.' -ForegroundColor Green
