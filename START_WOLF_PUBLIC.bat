@echo off
setlocal enableextensions
cd /d "%~dp0"
title WOLF Desk (public via Tailscale Funnel)

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
if not errorlevel 1 (
  echo Updating to %BRANCH% ...
  git fetch origin %BRANCH%
  git checkout %BRANCH%
  git pull --ff-only origin %BRANCH%
)

REM ---- access key (this is the ONLY guard once you're public - make it strong) ----
if not defined WOLF_PASS set /p WOLF_PASS=Enter your WOLF_PASS (access key):
if not defined WOLF_PASS (
  echo.
  echo No WOLF_PASS set - refusing to publish an OPEN desk to the internet.
  echo Tip: run  setx WOLF_PASS "a-long-random-key"  once, reopen this window.
  pause
  exit /b
)

REM ---- Tailscale present? ----
where tailscale >nul 2>&1
if errorlevel 1 (
  echo Tailscale not found. Install it from https://tailscale.com/download ,
  echo sign in once, then run this file again.
  pause
  exit /b
)

REM ---- start the desk server in its own window (inherits WOLF_PASS) ----
start "WOLF server" "%PY%" serve.py
timeout /t 3 /nobreak >nul

echo.
echo ============================================================
echo   Publishing WOLF Desk to the internet over HTTPS...
echo.
echo   Your phone (anywhere) opens the https://...ts.net address
echo   below, with  /app  on the end. Example:
echo       https://your-pc.tailXXXX.ts.net/app
echo.
echo   FIRST TIME ONLY: the command may print a link to ENABLE
echo   Funnel for your tailnet - open it once and approve.
echo   Stop everything with Ctrl+C, then close the server window.
echo ============================================================
echo.

REM ---- expose local port 8777 publicly over HTTPS (blocks here, prints the URL) ----
tailscale funnel 8777
