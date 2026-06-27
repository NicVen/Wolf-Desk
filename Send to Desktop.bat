@echo off
REM Recreate the WOLF dashboard shortcut on the Desktop (fixes a broken link).
powershell -NoProfile -ExecutionPolicy Bypass -Command "$proj=(Split-Path -Parent '%~f0'); $desk=[Environment]::GetFolderPath('Desktop'); $w=New-Object -ComObject WScript.Shell; $sc=$w.CreateShortcut((Join-Path $desk 'THE WOLF.lnk')); $sc.TargetPath=(Join-Path $proj 'START_WOLF.bat'); $sc.WorkingDirectory=$proj; $sc.IconLocation=(Join-Path $proj 'wolf.ico'); $sc.Description='THE WOLF PROJECT'; $sc.Save(); Write-Host ('Shortcut created: ' + (Join-Path $desk 'THE WOLF.lnk'))"
echo.
pause
