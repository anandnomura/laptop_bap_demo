@echo off
setlocal
cd /d "%~dp0\.."
py -3 enterprise_demo\orchestration\smoke_test.py
