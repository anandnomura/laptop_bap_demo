@echo off
setlocal
cd /d "%~dp0"

dotnet --list-sdks | findstr /r "^8\." >nul
if errorlevel 1 (
  echo .NET 8 SDK is required to build ClaudeGuard.
  exit /b 1
)

dotnet publish src\ClaudeGuard.csproj ^
  --configuration Release ^
  --runtime win-x64 ^
  --self-contained true ^
  -p:PublishSingleFile=true ^
  -p:PublishTrimmed=false ^
  -p:DebugType=None ^
  -p:DebugSymbols=false ^
  --output publish-self-contained

if errorlevel 1 exit /b 1
echo.
echo Built: %CD%\publish-self-contained\claude_guard.exe
echo This build includes the .NET runtime.
