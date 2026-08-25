@echo off
setlocal
cd /d "%~dp0"

where py >nul 2>nul
if errorlevel 1 (
  echo ERROR: Python launcher 'py' was not found. Install Python 3.11 or newer.
  exit /b 1
)

where claude >nul 2>nul
if errorlevel 1 (
  echo ERROR: Claude Code CLI was not found on PATH.
  echo Install and authenticate Claude Code, then run this file again.
  exit /b 1
)

py -3 setup_demo.py
if errorlevel 1 exit /b 1

start "Laptop BAP Demo Services" cmd /k "cd /d ""%~dp0"" && py -3 run_demo.py --no-browser"
py -3 wait_ready.py
if errorlevel 1 (
  echo ERROR: Demo services did not become ready. Check the services window.
  exit /b 1
)

start "" "http://127.0.0.1:8765/"

echo.
echo ================================================================
echo  LAPTOP BAP DEMO READY
echo ================================================================
echo  Dashboard: http://127.0.0.1:8765/
echo.
echo  Suggested Claude prompt:
echo  Read DEMO_SCRIPT.md and run Scenario 1 only. Explain each result.
echo.
echo  Exit Claude with /exit. Services continue until stop-demo.bat.
echo ================================================================
echo.

claude
endlocal

