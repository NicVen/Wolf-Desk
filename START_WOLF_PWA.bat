@echo off
setlocal enableextensions
cd /d "%~dp0"
title WOLF Desk (PWA)

REM ---- find a working Python ----
set "PY="
where py >nul 2>&1 && set "PY=py"
if not defined PY ( where python >nul 2>&1 && set "PY=python" )
if not defined PY for %%P in ("%LOCALAPPDATA%\Programs\Python\Python3*\python.exe") do set "PY=%%~fP"
if not defined PY (
  echo Python not found. Install from https://python.org and tick "Add to PATH".
  pause
  exit /b
)

REM ---- update to the Excalibur branch (skipped if git isn't installed) ----
set "BRANCH=claude/excalibur-v13-markov-omnibus-mm85xk"
where git >nul 2>&1
if errorlevel 1 (
  echo [warn] git not found - starting with the code already on disk.
) else (
  echo Updating to %BRANCH% ...
  git fetch origin %BRANCH%
  git checkout %BRANCH%
  git pull --ff-only origin %BRANCH%
  if errorlevel 1 echo [warn] git update had a problem - starting with the code on disk.
)

REM ---- access key (the PWA sends this as ?key=) ----
if not defined WOLF_PASS set /p WOLF_PASS=Enter your WOLF_PASS (access key):
if not defined WOLF_PASS (
  echo.
  echo No WOLF_PASS set - refusing to start OPEN on your network.
  echo Tip: run  setx WOLF_PASS "your-key"  once, reopen this window, and it is remembered.
  pause
  exit /b
)

REM ---- this PC's LAN IP, for the phone URL ----
set "IP="
for /f "usebackq delims=" %%i in (`powershell -NoProfile -Command "(Get-NetIPAddress -AddressFamily IPv4 ^| Where-Object {$_.IPAddress -notlike '127.*' -and $_.IPAddress -notlike '169.254.*'} ^| Sort-Object InterfaceMetric ^| Select-Object -First 1).IPAddress"`) do set "IP=%%i"

echo.
echo ============================================================
echo   WOLF Desk starting on this PC  (port 8777)
echo.
echo   On your PHONE (same Wi-Fi), open:
if defined IP (
  echo       http://%IP%:8777/app
) else (
  echo       http://YOUR-PC-IP:8777/app     ^(run  ipconfig  to find IPv4 Address^)
)
echo.
echo   Then: enter the same WOLF_PASS, tap Menu -^> Add to Home Screen.
echo   FIRST RUN: click ALLOW on the Windows Firewall popup (Private networks).
echo ============================================================
echo.

"%PY%" serve.py

echo.
echo WOLF server stopped. Close this window or press a key.
pause >nul
