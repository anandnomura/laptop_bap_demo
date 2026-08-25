@echo off
setlocal
cd /d "%~dp0"
start "" "http://127.0.0.1:11022/"
py -3 test_connector.py --dashboard
