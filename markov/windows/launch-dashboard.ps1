$projectDir = $PSScriptRoot
$posFile    = Join-Path $projectDir "window-position.json"
$serverJs   = Join-Path $projectDir "dashboard-server.js"
$port       = 3001

# ── Kill any existing dashboard server on port 3001 ───────────────────────────
$existing = Get-NetTCPConnection -LocalPort $port -State Listen -ErrorAction SilentlyContinue
if ($existing) {
    $pid_ = $existing | Select-Object -ExpandProperty OwningProcess -First 1
    if ($pid_) {
        Stop-Process -Id $pid_ -Force -ErrorAction SilentlyContinue
        Start-Sleep -Milliseconds 500
    }
}

# ── Start dashboard server in background ──────────────────────────────────────
$nodeProc = Start-Process "node" -ArgumentList "`"$serverJs`"" `
    -WorkingDirectory $projectDir `
    -WindowStyle Hidden `
    -PassThru

if (-not $nodeProc) {
    Add-Type -AssemblyName System.Windows.Forms
    [System.Windows.Forms.MessageBox]::Show(
        "Failed to start Node.js server.`nMake sure Node.js is installed.",
        "Markov Dashboard", 0, 48)
    exit 1
}

# ── Wait for server to be ready (max 20 seconds) ──────────────────────────────
$ready   = $false
$timeout = 20
$elapsed = 0
while ($elapsed -lt $timeout) {
    Start-Sleep -Milliseconds 500
    $elapsed += 0.5
    try {
        $r = Invoke-WebRequest -Uri "http://localhost:$port/api/status" `
            -UseBasicParsing -TimeoutSec 1 -ErrorAction Stop
        if ($r.StatusCode -eq 200) { $ready = $true; break }
    } catch {}
}

if (-not $ready) {
    Add-Type -AssemblyName System.Windows.Forms
    [System.Windows.Forms.MessageBox]::Show(
        "Dashboard server did not start in time.`nCheck that port $port is free.",
        "Markov Dashboard", 0, 48)
    exit 1
}

# ── Read saved window position ─────────────────────────────────────────────────
$winW = 460
$winH = 820
$winX = 0
$winY = 0
$usePos = $false

if (Test-Path $posFile) {
    try {
        $pos = Get-Content $posFile -Raw | ConvertFrom-Json
        if ($pos.x -ne $null -and $pos.y -ne $null) {
            $winX   = [int]$pos.x
            $winY   = [int]$pos.y
            $winW   = if ($pos.width)  { [int]$pos.width  } else { 460 }
            $winH   = if ($pos.height) { [int]$pos.height } else { 820 }
            $usePos = $true
        }
    } catch {}
}

# ── Find Edge or Chrome ────────────────────────────────────────────────────────
$browser = $null
$browserArgs = $null

$edgePaths = @(
    "$env:ProgramFiles\Microsoft\Edge\Application\msedge.exe",
    "${env:ProgramFiles(x86)}\Microsoft\Edge\Application\msedge.exe",
    "$env:LOCALAPPDATA\Microsoft\Edge\Application\msedge.exe"
)
foreach ($p in $edgePaths) {
    if (Test-Path $p) { $browser = $p; break }
}

if (-not $browser) {
    $chromePaths = @(
        "$env:ProgramFiles\Google\Chrome\Application\chrome.exe",
        "${env:ProgramFiles(x86)}\Google\Chrome\Application\chrome.exe",
        "$env:LOCALAPPDATA\Google\Chrome\Application\chrome.exe"
    )
    foreach ($p in $chromePaths) {
        if (Test-Path $p) { $browser = $p; break }
    }
}

if (-not $browser) {
    Add-Type -AssemblyName System.Windows.Forms
    [System.Windows.Forms.MessageBox]::Show(
        "Microsoft Edge or Google Chrome is required to display the dashboard.",
        "Markov Dashboard", 0, 48)
    exit 1
}

# ── Build browser args ─────────────────────────────────────────────────────────
$profileDir = Join-Path $projectDir ".dashboard-profile"
$args_ = @(
    "--app=http://localhost:$port",
    "--window-size=$winW,$winH",
    "--user-data-dir=`"$profileDir`"",
    "--no-first-run",
    "--no-default-browser-check",
    "--disable-extensions",
    "--disable-background-networking"
)
if ($usePos) {
    $args_ += "--window-position=$winX,$winY"
}

Start-Process $browser -ArgumentList ($args_ -join " ")

# ── Toast notification ─────────────────────────────────────────────────────────
try {
    Add-Type -AssemblyName System.Windows.Forms
    $n = New-Object System.Windows.Forms.NotifyIcon
    $n.Icon    = [System.Drawing.SystemIcons]::Information
    $n.BalloonTipTitle = "Markov Dashboard"
    $n.BalloonTipText  = "Dashboard is live at localhost:$port"
    $n.Visible = $true
    $n.ShowBalloonTip(3000)
    Start-Sleep -Seconds 3
    $n.Visible = $false
    $n.Dispose()
} catch {}
