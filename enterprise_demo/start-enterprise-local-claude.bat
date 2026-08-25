@echo off
setlocal
cd /d "%~dp0\.."

set "CLAUDE_EXE=%USERPROFILE%\.local\bin\claude.exe"
where claude >nul 2>nul
if not errorlevel 1 set "CLAUDE_EXE=claude"
if not exist "%CLAUDE_EXE%" if "%CLAUDE_EXE%" NEQ "claude" (
  echo ERROR: Claude Code was not found.
  exit /b 1
)

powershell -NoProfile -Command "try { $h=Invoke-RestMethod 'http://127.0.0.1:4080/health' -TimeoutSec 3; if (-not $h.ok) { exit 1 } } catch { exit 1 }"
if errorlevel 1 (
  echo ERROR: ccbridge is not ready on port 4080. Run local_poc\start-ccbridge.bat first.
  exit /b 1
)

enterprise_demo\claude_guard\publish\claude_guard.exe --health
if errorlevel 1 (
  echo ERROR: The named-pipe laptop connector is not ready.
  echo Run enterprise_demo\start-enterprise-demo.bat in another window.
  exit /b 1
)

powershell -NoProfile -Command "try { $h=Invoke-RestMethod 'http://127.0.0.1:11445/health' -TimeoutSec 3; if (-not $h.ok) { exit 1 } } catch { exit 1 }"
if errorlevel 1 (
  echo ERROR: The enterprise demo control plane is not ready.
  exit /b 1
)

set "ANTHROPIC_BASE_URL=http://127.0.0.1:4080"
set "ANTHROPIC_API_KEY=local-demo-key"
set "CLAUDE_CODE_DISABLE_NONESSENTIAL_TRAFFIC=1"

start "" "http://127.0.0.1:11445/"
echo.
echo Enterprise-shaped local Claude demo is ready.
echo Suggested prompt:
echo Run exactly this command and explain the returned BAP evidence:
echo ./enterprise_demo/bap_resource_client/publish/bap_resource_client.exe read customer-123
echo.
"%CLAUDE_EXE%" ^
  --settings enterprise_demo\claude-settings.enterprise-demo.json ^
  --model claude-3-5-sonnet-20241022 ^
  --tools Bash ^
  --system-prompt "You are a Windows command agent using Git Bash. Copy exact commands from the user verbatim into the Bash tool. Never simulate a tool result. After the tool returns, explain the actual BAP evidence."
endlocal
