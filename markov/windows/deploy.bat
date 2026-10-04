@echo off
echo.
echo ================================================
echo   Deploy Markov - Claude BOT to Railway
echo ================================================
echo.

cd /d "%~dp0"

:: Check node
node --version >nul 2>&1
if %errorlevel% neq 0 (
    echo   ERROR: Node.js not installed.
    echo   Run REINSTALL.bat in the CLAUDE folder first.
    pause & exit /b
)

:: Install dependencies
echo [1/4] Installing dependencies...
call npm install
echo       Done.

:: Install Railway CLI
echo.
echo [2/4] Installing Railway CLI...
call npm install -g @railway/cli
echo       Done.

:: Login
echo.
echo [3/4] Logging into Railway...
echo       A browser window will open. Sign in with GitHub or Google.
railway login

:: Deploy
echo.
echo [4/4] Deploying to Railway...
railway up

echo.
echo ================================================
echo   Deployment complete!
echo ================================================
echo.
echo   Environment variables to set in Railway dashboard:
echo      TELEGRAM_BOT_TOKEN  = (from config.json in CLAUDE folder)
echo      TELEGRAM_CHAT_ID    = (from config.json in CLAUDE folder)
echo      SCAN_INTERVAL_MIN   = 15
echo      QUIET_INTERVAL_MIN  = 60
echo.
echo   The bot will auto-scan 18 pairs every 15 min.
echo   Markov regime filter is built in - no extra setup needed.
echo.
pause
