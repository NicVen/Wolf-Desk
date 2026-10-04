$projectDir = $PSScriptRoot
$desktop    = [Environment]::GetFolderPath("Desktop")
$lnkPath    = Join-Path $desktop "Markov - Claude BOT.lnk"
$icoPath    = Join-Path $projectDir "markov-bot.ico"
$script     = Join-Path $projectDir "launch-dashboard.ps1"

# ── Draw a custom icon (dark bg + green chart line) ───────────────────────────
Add-Type -AssemblyName System.Drawing

function New-MarkovIcon($size) {
    $bmp = New-Object System.Drawing.Bitmap($size, $size)
    $g   = [System.Drawing.Graphics]::FromImage($bmp)
    $g.SmoothingMode     = [System.Drawing.Drawing2D.SmoothingMode]::AntiAlias
    $g.InterpolationMode = [System.Drawing.Drawing2D.InterpolationMode]::HighQualityBicubic

    # Background: near-black #0B0F0D
    $g.Clear([System.Drawing.Color]::FromArgb(11, 15, 13))

    # Rounded rect border in dark green
    $borderPen = New-Object System.Drawing.Pen([System.Drawing.Color]::FromArgb(40, 90, 60), [float]([math]::Max(1, $size / 32)))
    $g.DrawRectangle($borderPen, 0, 0, $size - 1, $size - 1)
    $borderPen.Dispose()

    # Scale chart points to icon size
    $m   = $size / 32.0
    $pts = [System.Drawing.PointF[]]@(
        [System.Drawing.PointF]::new( 3 * $m, 26 * $m),
        [System.Drawing.PointF]::new( 8 * $m, 21 * $m),
        [System.Drawing.PointF]::new(13 * $m, 23 * $m),
        [System.Drawing.PointF]::new(18 * $m, 13 * $m),
        [System.Drawing.PointF]::new(23 * $m,  9 * $m),
        [System.Drawing.PointF]::new(29 * $m,  4 * $m)
    )

    # Glow pass (wider, dimmer)
    $glowPen = New-Object System.Drawing.Pen([System.Drawing.Color]::FromArgb(60, 63, 222, 126), [float]([math]::Max(2, $size / 10)))
    $g.DrawCurve($glowPen, $pts, 0.4)
    $glowPen.Dispose()

    # Main line: accent green #3FDE7E
    $linePen = New-Object System.Drawing.Pen([System.Drawing.Color]::FromArgb(63, 222, 126), [float]([math]::Max(1, $size / 16)))
    $g.DrawCurve($linePen, $pts, 0.4)
    $linePen.Dispose()

    # Dot at the tip
    $dotR = [float]([math]::Max(1.5, $size / 10))
    $dotBrush = New-Object System.Drawing.SolidBrush([System.Drawing.Color]::FromArgb(63, 222, 126))
    $g.FillEllipse($dotBrush, [float](29 * $m - $dotR), [float](4 * $m - $dotR), $dotR * 2, $dotR * 2)
    $dotBrush.Dispose()

    $g.Dispose()
    return $bmp
}

# Build multi-size .ico (256, 48, 32, 16) for crisp display at all scales
$sizes = @(256, 48, 32, 16)
$bitmaps = $sizes | ForEach-Object { New-MarkovIcon $_ }

# Write proper ICO format manually
$ms = New-Object System.IO.MemoryStream

$writer = New-Object System.IO.BinaryWriter($ms)
$writer.Write([uint16]0)           # reserved
$writer.Write([uint16]1)           # type: ICO
$writer.Write([uint16]$sizes.Count)

# Image data blobs
$imageStreams = @()
foreach ($bmp in $bitmaps) {
    $s = New-Object System.IO.MemoryStream
    $bmp.Save($s, [System.Drawing.Imaging.ImageFormat]::Png)
    $imageStreams += $s
}

# Directory entries (6-byte header + 16 bytes per image)
$offset = 6 + 16 * $sizes.Count
for ($i = 0; $i -lt $sizes.Count; $i++) {
    $sz = $sizes[$i]
    $wh = if ($sz -ge 256) { 0 } else { $sz }
    $writer.Write([byte]$wh)   # width  (0 = 256)
    $writer.Write([byte]$wh)   # height (0 = 256)
    $writer.Write([byte]0)                          # color count
    $writer.Write([byte]0)                          # reserved
    $writer.Write([uint16]1)                        # planes
    $writer.Write([uint16]32)                       # bit count
    $writer.Write([uint32]$imageStreams[$i].Length) # size
    $writer.Write([uint32]$offset)                  # offset
    $offset += $imageStreams[$i].Length
}

# Image data
foreach ($s in $imageStreams) {
    $writer.Write($s.ToArray())
    $s.Dispose()
}

$writer.Flush()
[System.IO.File]::WriteAllBytes($icoPath, $ms.ToArray())
$ms.Dispose()

foreach ($bmp in $bitmaps) { $bmp.Dispose() }

Write-Host "  Icon created: $icoPath" -ForegroundColor Green

# ── Create / update desktop shortcut ──────────────────────────────────────────
$shell = New-Object -ComObject WScript.Shell
$lnk   = $shell.CreateShortcut($lnkPath)

$lnk.TargetPath       = "powershell.exe"
$lnk.Arguments        = "-ExecutionPolicy Bypass -File `"$script`""
$lnk.WorkingDirectory = $projectDir
$lnk.WindowStyle      = 1
$lnk.Description      = "Open Markov - Claude BOT Dashboard"
$lnk.IconLocation     = "$icoPath,0"
$lnk.Save()

Write-Host "  Shortcut updated: $lnkPath" -ForegroundColor Green
Write-Host ""
Write-Host "  Desktop icon is ready. Double-click to deploy." -ForegroundColor Cyan
Write-Host ""
