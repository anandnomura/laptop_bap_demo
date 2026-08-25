$ErrorActionPreference = "Stop"

$version = "4.12.0"
$expectedSha256 = "B22E013FD47023DBEAF87FC7C35CE14606CE1AFC8F4716463F8B8A0F855063BA"
$archiveName = "cedar-policy-cli-x86_64-pc-windows-msvc.zip"
$download = "https://github.com/cedar-policy/cedar/releases/download/cedar-policy-cli-v$version/$archiveName"
$toolDirectory = Join-Path $PSScriptRoot "..\runtime\tools\cedar-$version"
$executable = Join-Path $toolDirectory "cedar.exe"

if (Test-Path -LiteralPath $executable) {
    Write-Host "Cedar CLI $version is already installed at $executable"
    exit 0
}

$archive = Join-Path ([System.IO.Path]::GetTempPath()) "cedar-policy-cli-$version-windows.zip"
Invoke-WebRequest -Uri $download -OutFile $archive
$actualSha256 = (Get-FileHash -LiteralPath $archive -Algorithm SHA256).Hash
if ($actualSha256 -ne $expectedSha256) {
    throw "Cedar CLI checksum mismatch. Expected $expectedSha256; received $actualSha256"
}

New-Item -ItemType Directory -Force -Path $toolDirectory | Out-Null
Expand-Archive -LiteralPath $archive -DestinationPath $toolDirectory -Force
if (-not (Test-Path -LiteralPath $executable)) {
    throw "The Cedar archive did not contain cedar.exe"
}

Write-Host "Installed official Cedar CLI $version at $executable"
