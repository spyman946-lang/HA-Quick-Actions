$ErrorActionPreference = "Stop"
Set-Location $PSScriptRoot

if (-not (Get-Command pyinstaller -ErrorAction SilentlyContinue)) {
    python -m pip install pyinstaller
}

$distDir = Join-Path $PSScriptRoot "dist"
$exePath = Join-Path $distDir "HA-Quick-Actions.exe"
$workDir = Join-Path $PSScriptRoot "build"

if (Test-Path $exePath) {
    try {
        $fs = [System.IO.File]::Open(
            $exePath,
            [System.IO.FileMode]::Open,
            [System.IO.FileAccess]::ReadWrite,
            [System.IO.FileShare]::None
        )
        $fs.Close()
    }
    catch {
        $distDir = Join-Path $PSScriptRoot "dist_rebuild"
        $workDir = Join-Path $PSScriptRoot "build_rebuild"
        Write-Host "dist\HA-Quick-Actions.exe is locked. Building to:" -ForegroundColor Yellow
        Write-Host "  $distDir" -ForegroundColor Yellow
    }
}

$outExe = Join-Path $distDir "HA-Quick-Actions.exe"

# Smaller onefile: no --collect-all; exclude heavy optional deps; bytecode optimize 2 (target under ~25 MB).
python -m PyInstaller `
    --onefile `
    --windowed `
    --noconfirm `
    --clean `
    --optimize 2 `
    --name "HA-Quick-Actions" `
    --distpath $distDir `
    --workpath $workDir `
    --exclude-module numpy `
    --exclude-module scipy `
    --exclude-module pandas `
    --exclude-module matplotlib `
    --exclude-module sklearn `
    --exclude-module cv2 `
    --exclude-module clr `
    --exclude-module pythonnet `
    --exclude-module unittest `
    --exclude-module test `
    --exclude-module pydoc_data `
    main.py

$bytes = (Get-Item $outExe).Length
$mb = [math]::Round($bytes / 1MB, 2)
Write-Host "OK: $outExe  ($mb MB)" -ForegroundColor Green
if ($mb -ge 25) {
    Write-Host "Warning: exe is >= 25 MB. Try a clean venv with only requests, pystray, Pillow." -ForegroundColor Yellow
}
if ($distDir -like "*dist_rebuild*") {
    Write-Host "Copy exe to dist\ after closing the old app, or run from dist_rebuild\" -ForegroundColor Cyan
}
