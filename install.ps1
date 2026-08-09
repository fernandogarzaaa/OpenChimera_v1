# OpenChimera v2 — One-command installer (Windows PowerShell)
# Usage: irm https://raw.githubusercontent.com/fernandogarzaaa/OpenChimera_v2/main/install.ps1 | iex
#   OR:   .\install.ps1

Set-StrictMode -Version Latest
$ErrorActionPreference = 'Stop'

$banner = @"
   ___                    ____ _     _                        __      _____
  / _ \ _ __   ___ _ __  / ___| |__ (_)_ __ ___   ___ _ __ __ \ \    / /__ \
 | | | | '_ \ / _ \ '_ \| |   | '_ \| | '_ ` _ \ / _ \ '__/ _` \ \  / /  / /
 | |_| | |_) |  __/ | | | |___| | | | | | | | | |  __/ | | (_| |\ \/ /  / /_
  \___/| .__/ \___|_| |_|\____|_| |_|_|_| |_| |_|
\___|_|  \__,_| \__/  |____|
       |_|
                      v2 Agentic Orchestration Runtime
"@

Write-Host $banner -ForegroundColor Cyan
Write-Host ""

# ── Helpers ──────────────────────────────────────────────────────────────
function Test-Command($cmd) {
    return [bool](Get-Command $cmd -ErrorAction SilentlyContinue)
}

function Invoke-Step($msg, $script) {
    Write-Host "[OPENCHIMERA] $msg" -ForegroundColor Yellow
    try {
        & $script
        if ($LASTEXITCODE -ne 0 -and $LASTEXITCODE -ne $null) { throw "Exit code $LASTEXITCODE" }
        Write-Host "  ✓ Done" -ForegroundColor Green
    } catch {
        Write-Host "  ✗ Failed: $_" -ForegroundColor Red
        throw
    }
}

# ── 1. Detect repo root ──────────────────────────────────────────────────
$repoRoot = $PSScriptRoot
if (-not $repoRoot) { $repoRoot = (Get-Location).Path }
Write-Host "Repo root: $repoRoot" -ForegroundColor DarkGray

# ── 2. Check Python 3.11+ ────────────────────────────────────────────────
Write-Host "[1/8] Checking Python 3.11+..." -ForegroundColor Yellow
$pythonCmd = $null
foreach ($c in @("python", "python3", "py")) {
    try {
        $ver = & $c --version 2>&1
        if ($ver -match "Python (\d+)\.(\d+)") {
            if ([int]$Matches[1] -ge 3 -and [int]$Matches[2] -ge 11) {
                $pythonCmd = $c
                break
            }
        }
    } catch {}
}
if (-not $pythonCmd) {
    Write-Host "Python 3.11+ is required. Download from https://www.python.org/downloads/" -ForegroundColor Red
    exit 1
}
Write-Host "  Found: $( & $pythonCmd --version 2>&1 )" -ForegroundColor Green

# ── 3. Check Rust ────────────────────────────────────────────────────────
Write-Host "[2/8] Checking Rust toolchain..." -ForegroundColor Yellow
if (-not (Test-Command "cargo")) {
    Write-Host "  Rust not found. Installing via rustup..." -ForegroundColor DarkYellow
    $rustup = Invoke-RestMethod https://win.rustup.rs/x86_64 -UseBasicParsing
    $tmp = [System.IO.Path]::GetTempFileName() + ".exe"
    [System.IO.File]::WriteAllBytes($tmp, $rustup)
    & $tmp -y --default-toolchain stable
    $env:PATH += ";$env:USERPROFILE\.cargo\bin"
    # Reload PATH for this session
    $env:PATH = [Environment]::GetEnvironmentVariable("PATH", "Machine") + ";" + [Environment]::GetEnvironmentVariable("PATH", "User")
}
Write-Host "  Found: $(cargo --version)" -ForegroundColor Green

# ── 4. Check Node (optional) ─────────────────────────────────────────────
$hasNode = Test-Command "node"
if ($hasNode) {
    Write-Host "[3/8] Node found: $(node --version)" -ForegroundColor Green
} else {
    Write-Host "[3/8] Node not found — TypeScript dashboard will be skipped." -ForegroundColor DarkYellow
}

# ── 5. Create venv ───────────────────────────────────────────────────────
Write-Host "[4/8] Creating Python virtual environment..." -ForegroundColor Yellow
$venvPath = Join-Path $repoRoot ".venv"
if (-not (Test-Path (Join-Path $venvPath "Scripts" "python.exe"))) {
    & $pythonCmd -m venv $venvPath
}
$venvPython = Join-Path $venvPath "Scripts" "python.exe"
$venvPip = Join-Path $venvPath "Scripts" "pip.exe"
Write-Host "  venv ready" -ForegroundColor Green

# ── 6. Install Python package ────────────────────────────────────────────
Write-Host "[5/8] Installing Python dependencies..." -ForegroundColor Yellow
& $venvPip install --upgrade pip -q
& $venvPip install -e $repoRoot -q
if ($LASTEXITCODE -ne 0) {
    Write-Host "Python install failed. Retrying with output..." -ForegroundColor Red
    & $venvPip install -e $repoRoot
    exit 1
}
Write-Host "  Python package installed" -ForegroundColor Green

# ── 7. Build Rust TUI ────────────────────────────────────────────────────
Write-Host "[6/8] Building Rust TUI..." -ForegroundColor Yellow
Push-Location (Join-Path $repoRoot "crates" "chimera-tui")
& cargo build --release
if ($LASTEXITCODE -ne 0) {
    Write-Host "Rust build failed." -ForegroundColor Red
    Pop-Location
    exit 1
}
Pop-Location
Write-Host "  Rust TUI built" -ForegroundColor Green

# ── 8. Build TypeScript dashboard (optional) ─────────────────────────────
if ($hasNode) {
    Write-Host "[7/8] Building TypeScript dashboard..." -ForegroundColor Yellow
    Push-Location (Join-Path $repoRoot "typescript" "dashboard")
    & npm install
    if ($LASTEXITCODE -ne 0) { Write-Host "  npm install failed, skipping dashboard build" -ForegroundColor DarkYellow }
    else {
        & npm run build
        if ($LASTEXITCODE -ne 0) { Write-Host "  dashboard build failed, skipping" -ForegroundColor DarkYellow }
        else { Write-Host "  Dashboard built" -ForegroundColor Green }
    }
    Pop-Location
} else {
    Write-Host "[7/8] Skipping dashboard (Node not found)" -ForegroundColor DarkYellow
}

# ── 9. Bootstrap config ──────────────────────────────────────────────────
Write-Host "[8/8] Bootstrapping config..." -ForegroundColor Yellow
$localConfig = Join-Path $repoRoot "config" "local.yaml"
if (-not (Test-Path $localConfig)) {
    @"
# Local overrides — safe to edit
server:
  host: "127.0.0.1"
  port: 7870

providers:
  openai:
    enabled: true
    api_key: ""
  anthropic:
    enabled: true
    api_key: ""
  google:
    enabled: true
    api_key: ""
  groq:
    enabled: true
    api_key: ""
  ollama:
    enabled: true
"@ | Set-Content -Path $localConfig -Encoding UTF8
}
Write-Host "  Config ready" -ForegroundColor Green

# ── Done ─────────────────────────────────────────────────────────────────
Write-Host ""
Write-Host "╔══════════════════════════════════════════════════════════════════╗" -ForegroundColor Cyan
Write-Host "║          OpenChimera v2 Installation Complete                   ║" -ForegroundColor Cyan
Write-Host "╚══════════════════════════════════════════════════════════════════╝" -ForegroundColor Cyan
Write-Host ""
Write-Host "Next steps:" -ForegroundColor White
Write-Host "  1. Edit config:    notepad config\local.yaml" -ForegroundColor White
Write-Host "  2. Start server:   .venv\Scripts\openchimera serve" -ForegroundColor White
Write-Host "  3. Launch TUI:     .\target\release\openchimera.exe --demo" -ForegroundColor White
Write-Host "  4. Run doctor:     .venv\Scripts\openchimera doctor" -ForegroundColor White
Write-Host ""
Write-Host "API docs: http://127.0.0.1:7870/docs" -ForegroundColor Cyan
Write-Host ""
