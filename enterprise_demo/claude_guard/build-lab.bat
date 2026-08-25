@echo off
setlocal
cd /d "%~dp0"

dotnet --list-sdks | findstr /r "^8\." >nul
if errorlevel 1 (
  echo .NET 8 SDK is required to build ClaudeGuard.
  exit /b 1
)

dotnet publish src\ClaudeGuard.csproj ^
  --configuration Lab ^
  --runtime win-x64 ^
  --self-contained false ^
  -p:PublishSingleFile=true ^
  -p:DebugType=None ^
  -p:DebugSymbols=false ^
  --output publish-lab

if errorlevel 1 exit /b 1
echo.
echo Built: %CD%\publish-lab\claude_guard_lab.exe
echo WARNING: This lab executable contains a bypass capability.
echo Never sign, deploy, or allowlist it on a controlled laptop.
