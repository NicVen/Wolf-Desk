@echo off
setlocal enableextensions
cd /d "%~dp0"
title WOLF MT5 bridge (VPS -> this PC)

REM ---- find Python ----
set "PY="
where py >nul 2>&1 && set "PY=py"
if not defined PY ( where python >nul 2>&1 && set "PY=python" )
if not defined PY (
  echo Python not found. Install from https://python.org and tick "Add to PATH".
  pause
  exit /b
)

REM ---- your VPS address + key (set these once with setx to make them stick) ----
if not defined WOLF_HOST set "WOLF_HOST=https://178.104.88.38.sslip.io"
if not defined WOLF_PASS set /p WOLF_PASS=Enter your WOLF_PASS (access key):
if not defined WOLF_PASS ( echo No WOLF_PASS - aborting. & pause & exit /b )

echo.
echo Pulling Markov regimes from %WOLF_HOST% every 5 min and writing MT5 gate files.
echo Point each EA's InpMarkovFile at markov_^<SYMBOL^>.txt (Gold uses markov_regime.txt).
echo Ctrl+C to stop.
echo.

"%PY%" pc_bridge.py
