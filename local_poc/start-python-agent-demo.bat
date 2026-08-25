@echo off
setlocal
cd /d "%~dp0"

where py >nul 2>nul
if errorlevel 1 (
  echo ERROR: Python launcher 'py' was not found. Install Python 3.10 or newer.
  exit /b 1
)

start "Laptop BAP Demo Services" cmd /k "cd /d ""%~dp0"" && py -3 run_demo.py --no-browser"
py -3 wait_ready.py
if errorlevel 1 (
  echo ERROR: Demo services did not become ready. Check the services window.
  exit /b 1
)

start "" "http://127.0.0.1:8765/"
set "BAP_AGENT_LLM_URL=http://127.0.0.1:8080/v1/chat/completions"
echo.
echo Running the local-LLM Python agent. Keep the dashboard visible.
echo LLM endpoint: %BAP_AGENT_LLM_URL%
echo.
py -3 python_agent.py --llm-url "%BAP_AGENT_LLM_URL%"
endlocal
