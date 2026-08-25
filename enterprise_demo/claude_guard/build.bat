@echo off
setlocal
cd /d "%~dp0"

dotnet --list-sdks | findstr /r "^8\." >nul
if errorlevel 1 (
  echo .NET 8 SDK is required to build ClaudeGuard.
  echo The .NET runtime alone is not sufficient.
  echo Install the SDK from https://dotnet.microsoft.com/download/dotnet/8.0
  exit /b 1
)

dotnet publish src\ClaudeGuard.csproj ^
  --configuration Release ^
  --runtime win-x64 ^
  --self-contained false ^
  -p:PublishSingleFile=true ^
  -p:DebugType=None ^
  -p:DebugSymbols=false ^
  --output publish

if errorlevel 1 exit /b 1
echo.
echo Built: %CD%\publish\claude_guard.exe
echo This build requires the .NET 8 runtime on the target laptop.
