@echo off
setlocal
cd /d "%~dp0"

set "CLAUDE_EXE=%USERPROFILE%\.local\bin\claude.exe"
where claude >nul 2>nul
if not errorlevel 1 set "CLAUDE_EXE=claude"
if not exist "%CLAUDE_EXE%" if "%CLAUDE_EXE%" NEQ "claude" (
  echo ERROR: Claude Code was not found on PATH or at %USERPROFILE%\.local\bin\claude.exe
  exit /b 1
)

powershell -NoProfile -Command "try { $h=Invoke-RestMethod 'http://127.0.0.1:4080/health' -TimeoutSec 5; if (-not $h.ok) { exit 1 } } catch { exit 1 }"
if errorlevel 1 (
  echo ERROR: The updated ccbridge is not ready at http://127.0.0.1:4080/health
  echo Run start-ccbridge.bat in a separate window first.
  exit /b 1
)

py -3 wait_ready.py
if errorlevel 1 (
  echo ERROR: The BAP demo services are not ready. Start run_demo.py in another window.
  exit /b 1
)

set "ANTHROPIC_BASE_URL=http://127.0.0.1:4080"
set "ANTHROPIC_API_KEY=local-demo-key"
set "CLAUDE_CODE_DISABLE_NONESSENTIAL_TRAFFIC=1"

start "" "http://127.0.0.1:8765/"
echo.
echo Local Claude Code is connected through ccbridge to Qwen on port 8080.
echo Suggested prompt:
echo Call Bash exactly once with this exact command: py -3 tools/db_client.py read customer-123
echo.
"%CLAUDE_EXE%" ^
  --model claude-3-5-sonnet-20241022 ^
  --tools Bash ^
  --system-prompt "You are a Windows command agent using Git Bash. Copy exact commands from the user verbatim into the Bash tool. Never substitute example paths or simulate results. After receiving a tool result, answer from it."
endlocal
