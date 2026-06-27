@echo off
cd /d "%~dp0"
REM --- find a working Python (python / py / installed location) ---
set "PY="
where py >nul 2>&1 && set "PY=py"
if not defined PY ( where python >nul 2>&1 && set "PY=python" )
if not defined PY for %%P in ("%LOCALAPPDATA%\Programs\Python\Python3*\python.exe") do set "PY=%%~fP"
if not defined PY for %%P in ("C:\Python3*\python.exe") do set "PY=%%~fP"
if not defined PY (
  echo Python not found. Install it from https://python.org and tick "Add to PATH".
  pause
  exit /b
)
REM --- start server in its own window, then open the dashboard ---
start "WOLF server" "%PY%" serve.py
timeout /t 3 /nobreak >nul
start "" http://localhost:8777
exit
