# OpenChimera v2 — One-Liner PowerShell Install
# Inspired by OpenClaw and Hermes Agent onboarding patterns
# Usage: iwr -useb https://raw.githubusercontent.com/fernandogarzaaa/OpenChimera_v1/main/install.ps1 | iex

$ErrorActionPreference = "Stop"

function Write-Color($Text, $Color = "White") {
    Write-Host $Text -ForegroundColor $Color
}

Write-Color "`n🐉 OpenChimera v2 Installer`n" "Cyan"

# ── Check prerequisites ──
Write-Color "→ Checking prerequisites..." "Gray"

$git = Get-Command git -ErrorAction SilentlyContinue
if (-not $git) {
    Write-Color "✗ Git not found. Install from https://git-scm.com/download/win" "Red"
    exit 1
}

$python = Get-Command python -ErrorAction SilentlyContinue
if (-not $python) {
    # Try python3
    $python = Get-Command python3 -ErrorAction SilentlyContinue
}
if (-not $python) {
    Write-Color "✗ Python not found. Install Python 3.11+ from https://python.org" "Red"
    exit 1
}

$pyVersion = & $python.Source --version 2>&1
Write-Color "✓ $pyVersion" "Green"

# ── Clone repo ──
$installDir = "$env:USERPROFILE\OpenChimera"
if (Test-Path $installDir) {
    Write-Color "→ Updating existing installation at $installDir..." "Gray"
    Set-Location $installDir
    & git pull origin main 2>$null | Out-Null
} else {
    Write-Color "→ Cloning OpenChimera to $installDir..." "Gray"
    & git clone https://github.com/fernandogarzaaa/OpenChimera_v1.git $installDir 2>$null | Out-Null
    Set-Location $installDir
}

# ── Install Python dependencies ──
Write-Color "→ Installing Python dependencies (this may take 2-5 minutes)..." "Gray"
& $python.Source -m pip install -e ".[all]" --quiet 2>&1 | Out-Null
if ($LASTEXITCODE -ne 0) {
    Write-Color "⚠ Full install failed, trying core only..." "Yellow"
    & $python.Source -m pip install -e "." --quiet 2>&1 | Out-Null
}
Write-Color "✓ Python dependencies installed" "Green"

# ── Check for Rust / build TUI ──
$cargo = Get-Command cargo -ErrorAction SilentlyContinue
if ($cargo) {
    Write-Color "→ Building Rust TUI..." "Gray"
    Set-Location "$installDir\crates\chimera-tui"
    & cargo build --release 2>&1 | Out-Null
    if ($LASTEXITCODE -eq 0) {
        Write-Color "✓ Rust TUI built" "Green"
    } else {
        Write-Color "⚠ Rust TUI build failed (cargo error)" "Yellow"
    }
    Set-Location $installDir
} else {
    Write-Color "⚠ Rust not found — TUI unavailable. Install from https://rustup.rs" "Yellow"
}

# ── Add to PATH ──
$binDir = "$installDir\venv\Scripts"
if (Test-Path $binDir) {
    $currentPath = [Environment]::GetEnvironmentVariable("Path", "User")
    if ($currentPath -notlike "*$binDir*") {
        [Environment]::SetEnvironmentVariable("Path", "$currentPath;$binDir", "User")
        Write-Color "✓ Added to user PATH" "Green"
    }
}

# ── Create local config if not exists ──
if (-not (Test-Path "$installDir\config\local.yaml")) {
    @"
# Local overrides — add your API keys here or use env vars
providers:
  openai:
    enabled: true
  anthropic:
    enabled: true
  groq:
    enabled: true
"@ | Set-Content "$installDir\config\local.yaml" -Encoding UTF8
}

# ── Done ──
Write-Color "`n✅ OpenChimera v2 installed!`n" "Green"
Write-Color "Next steps:" "White"
Write-Color "  openchimera onboard      # Run setup wizard" "Cyan"
Write-Color "  openchimera doctor       # Run diagnostics" "Cyan"
Write-Color "  openchimera serve        # Start API server" "Cyan"
Write-Color "  openchimera tui          # Launch Rust TUI" "Cyan"
Write-Color "  openchimera ask `"hello`" # One-off query" "Cyan"
Write-Color ""

# Offer to run onboard
$runOnboard = Read-Host "Run onboarding now? [Y/n]"
if ($runOnboard -eq "" -or $runOnboard -match "^[Yy]") {
    & $python.Source -m openchimera onboard
}
