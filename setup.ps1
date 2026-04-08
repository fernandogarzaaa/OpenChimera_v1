#!/usr/bin/env pwsh
# OpenChimera — One-command setup for Windows
# Usage:  .\setup.ps1
#
# This script:
#   1. Checks Python is installed (3.11+)
#   2. Creates a virtual environment
#   3. Installs all dependencies
#   4. Bootstraps workspace state
#   5. Runs diagnostics
#   6. Tells you the single command to start

Set-StrictMode -Version Latest
$ErrorActionPreference = 'Stop'

$banner = @"

   ___                    ____ _     _
  / _ \ _ __   ___ _ __  / ___| |__ (_)_ __ ___   ___ _ __ __ _
 | | | | '_ \ / _ \ '_ \| |   | '_ \| | '_ ` _ \ / _ \ '__/ _` |
 | |_| | |_) |  __/ | | | |___| | | | | | | | | |  __/ | | (_| |
  \___/| .__/ \___|_| |_|\____|_| |_|_|_| |_| |_|\___|_|  \__,_|
       |_|
                         Setup Wizard

"@

Write-Host $banner -ForegroundColor Cyan

# ── Step 1: Check Python ─────────────────────────────────────────────────
Write-Host "[1/5] Checking Python..." -ForegroundColor Yellow

$pythonCmd = $null
foreach ($candidate in @("python", "python3", "py")) {
    try {
        $ver = & $candidate --version 2>&1
        if ($ver -match "Python (\d+)\.(\d+)") {
            $major = [int]$Matches[1]
            $minor = [int]$Matches[2]
            if ($major -ge 3 -and $minor -ge 11) {
                $pythonCmd = $candidate
                break
            }
        }
    } catch { }
}

if (-not $pythonCmd) {
    Write-Host ""
    Write-Host "  Python 3.11+ is required but was not found." -ForegroundColor Red
    Write-Host "  Install it from https://www.python.org/downloads/" -ForegroundColor Red
    Write-Host "  Make sure to check 'Add Python to PATH' during install." -ForegroundColor Red
    Write-Host ""
    exit 1
}

$pyVersion = & $pythonCmd --version 2>&1
Write-Host "  Found $pyVersion" -ForegroundColor Green

# ── Step 2: Create virtual environment ───────────────────────────────────
Write-Host "[2/5] Creating virtual environment..." -ForegroundColor Yellow

$venvPath = Join-Path $PSScriptRoot ".venv"
if (Test-Path (Join-Path $venvPath "Scripts" "python.exe")) {
    Write-Host "  Virtual environment already exists — reusing it" -ForegroundColor Green
} else {
    & $pythonCmd -m venv $venvPath
    if ($LASTEXITCODE -ne 0) {
        Write-Host "  Failed to create virtual environment." -ForegroundColor Red
        exit 1
    }
    Write-Host "  Created .venv" -ForegroundColor Green
}

$venvPython = Join-Path $venvPath "Scripts" "python.exe"
$venvPip    = Join-Path $venvPath "Scripts" "pip.exe"

# ── Step 3: Install dependencies ─────────────────────────────────────────
Write-Host "[3/5] Installing dependencies (this may take a minute)..." -ForegroundColor Yellow

& $venvPip install --upgrade pip --quiet 2>&1 | Out-Null
& $venvPip install -e $PSScriptRoot --quiet 2>&1 | Out-Null
if ($LASTEXITCODE -ne 0) {
    Write-Host "  Dependency install failed. Re-running with output:" -ForegroundColor Red
    & $venvPip install -e $PSScriptRoot
    exit 1
}
Write-Host "  All dependencies installed" -ForegroundColor Green

# ── Step 4: Bootstrap workspace ──────────────────────────────────────────
Write-Host "[4/5] Bootstrapping workspace..." -ForegroundColor Yellow

& $venvPython -c "from core.bootstrap import bootstrap_workspace; r = bootstrap_workspace(); print(f'  Created {len(r[""created_directories""])} dirs, {len(r[""created_files""])} files')"
if ($LASTEXITCODE -ne 0) {
    Write-Host "  Bootstrap had issues but the server may still work." -ForegroundColor DarkYellow
} else {
    Write-Host "  Workspace ready" -ForegroundColor Green
}

# ── Step 5: Run diagnostics ─────────────────────────────────────────────
Write-Host "[5/6] Running diagnostics..." -ForegroundColor Yellow

$openchimera = Join-Path $venvPath "Scripts" "openchimera.exe"
if (Test-Path $openchimera) {
    & $openchimera doctor 2>&1 | ForEach-Object { Write-Host "  $_" }
} else {
    & $venvPython (Join-Path $PSScriptRoot "run.py") doctor 2>&1 | ForEach-Object { Write-Host "  $_" }
}

# ── Step 6: Interactive setup wizard ─────────────────────────────────────
Write-Host ""
Write-Host "[6/6] Launching interactive setup wizard..." -ForegroundColor Yellow
Write-Host ""

if (Test-Path $openchimera) {
    & $openchimera setup --skip-wizard:$false 2>&1 | ForEach-Object { Write-Host $_ }
} else {
    & $venvPython -c "from core.setup_wizard import run_wizard; run_wizard()"
}

# ── Done ─────────────────────────────────────────────────────────────────
Write-Host ""
Write-Host "  Setup complete!" -ForegroundColor Green
Write-Host ""
Write-Host "  To start OpenChimera:" -ForegroundColor Cyan
Write-Host ""
Write-Host "    .venv\Scripts\Activate.ps1" -ForegroundColor White
Write-Host "    openchimera serve" -ForegroundColor White
Write-Host ""
Write-Host "  Then open http://127.0.0.1:7870/docs in your browser." -ForegroundColor Cyan
Write-Host ""
