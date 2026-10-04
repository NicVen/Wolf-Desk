$projectDir = $PSScriptRoot

Write-Host ""
Write-Host "  ============================================" -ForegroundColor Cyan
Write-Host "   Markov - Claude BOT  -  Railway Deploy" -ForegroundColor Cyan
Write-Host "  ============================================" -ForegroundColor Cyan
Write-Host ""

try {

# ── Check Node.js ──────────────────────────────────────────────────────────────
$nodeVer = node --version 2>&1
if ($LASTEXITCODE -ne 0) {
    Write-Host "  ERROR: Node.js not found." -ForegroundColor Red
    Write-Host "  Install from https://nodejs.org then try again." -ForegroundColor Yellow
    throw "nodejs missing"
}
Write-Host "  Node.js: $nodeVer  [OK]" -ForegroundColor Green

# ── Install npm dependencies if needed ─────────────────────────────────────────
if (-not (Test-Path (Join-Path $projectDir "node_modules\express"))) {
    Write-Host "  Installing dependencies..." -ForegroundColor Cyan
    Set-Location $projectDir
    npm install --silent 2>&1 | Out-Null
    Write-Host "  Dependencies: installed  [OK]" -ForegroundColor Green
} else {
    Write-Host "  Dependencies: already installed  [OK]" -ForegroundColor Green
}

# ── Check / install Railway CLI ────────────────────────────────────────────────
Write-Host ""
$railwayOk = $false
try { railway --version 2>&1 | Out-Null; if ($LASTEXITCODE -eq 0) { $railwayOk = $true } } catch {}
if (-not $railwayOk) {
    Write-Host "  Railway CLI not found. Installing..." -ForegroundColor Cyan
    npm install -g @railway/cli 2>&1 | Out-Null
    Write-Host "  Railway CLI: installed  [OK]" -ForegroundColor Green
} else {
    Write-Host "  Railway CLI: found  [OK]" -ForegroundColor Green
}

# ── Login check ────────────────────────────────────────────────────────────────
Write-Host ""
Write-Host "  Checking Railway login..." -ForegroundColor Cyan
$whoami = railway whoami 2>&1
if ($LASTEXITCODE -ne 0 -or "$whoami" -like "*not logged*") {
    Write-Host "  Not logged in -- opening browser..." -ForegroundColor Yellow
    railway login
    Write-Host "  Railway: logged in  [OK]" -ForegroundColor Green
} else {
    Write-Host "  Railway: $whoami  [OK]" -ForegroundColor Green
}

# ── Check project link ─────────────────────────────────────────────────────────
Write-Host ""
Write-Host "  Checking project link..." -ForegroundColor Cyan

$railwayCfg = Join-Path $env:USERPROFILE ".railway\config.json"
$isLinked   = $false

if (Test-Path $railwayCfg) {
    try {
        $cfg = Get-Content $railwayCfg -Raw | ConvertFrom-Json
        if ($cfg.projects -and $cfg.projects.PSObject.Properties[$projectDir]) {
            $isLinked = $true
        }
    } catch {}
}

if (-not $isLinked) {
    Write-Host "  Not linked -- connecting to Railway project..." -ForegroundColor Cyan
    $configPath = Join-Path (Split-Path $projectDir -Parent) "config.json"
    $projectId  = $null
    $serviceId  = $null
    if (Test-Path $configPath) {
        try {
            $botCfg    = Get-Content $configPath -Raw | ConvertFrom-Json
            $projectId = $botCfg.railway_project_id
            $serviceId = $botCfg.railway_service_id
        } catch {}
    }
    if (-not $projectId) {
        Write-Host "  Could not find project ID in config.json." -ForegroundColor Red
        Write-Host "  Open a terminal in this folder and run: railway link" -ForegroundColor Yellow
        throw "no project id"
    }
    Set-Location $projectDir
    if ($serviceId) {
        railway link -p $projectId -s $serviceId 2>&1 | Out-Null
    } else {
        railway link -p $projectId 2>&1 | Out-Null
    }
    Write-Host "  Project: linked  [OK]" -ForegroundColor Green
} else {
    Write-Host "  Project: already linked  [OK]" -ForegroundColor Green
}

# ── Deploy ─────────────────────────────────────────────────────────────────────
Write-Host ""
Write-Host "  Deploying to Railway..." -ForegroundColor Cyan
Write-Host "  (uploading files - takes about 60 seconds)" -ForegroundColor DarkGray
Write-Host ""

Set-Location $projectDir
railway up

if ($LASTEXITCODE -eq 0) {
    Write-Host ""
    Write-Host "  ============================================" -ForegroundColor Green
    Write-Host "   Deployed successfully!" -ForegroundColor Green
    Write-Host "  ============================================" -ForegroundColor Green
    Write-Host ""
    Write-Host "  Bot is live. Send /scan to Telegram to test." -ForegroundColor Cyan

    $configPath = Join-Path (Split-Path $projectDir -Parent) "config.json"
    if (Test-Path $configPath) {
        try {
            $botCfg = Get-Content $configPath -Raw | ConvertFrom-Json
            Write-Host ""
            Write-Host "  Railway env vars (set in dashboard if not already done):" -ForegroundColor DarkGray
            Write-Host "    TELEGRAM_BOT_TOKEN  = $($botCfg.telegram_bot_token)" -ForegroundColor DarkGray
            Write-Host "    TELEGRAM_CHAT_ID    = $($botCfg.telegram_chat_id)" -ForegroundColor DarkGray
            Write-Host "    SCAN_INTERVAL_MIN   = 15" -ForegroundColor DarkGray
            Write-Host "    QUIET_INTERVAL_MIN  = 60" -ForegroundColor DarkGray
        } catch {}
    }

    try {
        Add-Type -AssemblyName System.Windows.Forms
        $n = New-Object System.Windows.Forms.NotifyIcon
        $n.Icon    = [System.Drawing.SystemIcons]::Information
        $n.BalloonTipTitle = "Markov - Claude BOT"
        $n.BalloonTipText  = "Deployed to Railway successfully!"
        $n.Visible = $true
        $n.ShowBalloonTip(4000)
        Start-Sleep -Seconds 4
        $n.Visible = $false
        $n.Dispose()
    } catch {}

} else {
    Write-Host ""
    Write-Host "  Deploy failed. See errors above." -ForegroundColor Red
    Write-Host "  If 'no linked project': open a terminal here and run: railway link" -ForegroundColor Yellow
}

} catch {
    Write-Host ""
    Write-Host "  Error: $_" -ForegroundColor Red
}

Write-Host ""
Read-Host "  Press Enter to close"
