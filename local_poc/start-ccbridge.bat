@echo off
setlocal
cd /d "%~dp0"

powershell -NoProfile -Command "try { $m=(Invoke-RestMethod 'http://127.0.0.1:8080/v1/models' -TimeoutSec 5).data; if (-not $m) { exit 1 } } catch { exit 1 }"
if errorlevel 1 (
  echo ERROR: The OpenAI-compatible local model is not ready at http://127.0.0.1:8080/v1/models
  exit /b 1
)

echo Starting the Anthropic-compatible Claude Code bridge.
echo Local model: http://127.0.0.1:8080/v1
echo Claude bridge: http://127.0.0.1:4080
echo Leave this window open. Press Ctrl+C to stop it.
echo.
py -3 -m uvicorn ccbridge:app --host 127.0.0.1 --port 4080
endlocal
