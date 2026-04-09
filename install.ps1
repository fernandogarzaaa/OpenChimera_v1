# OpenChimera one-liner install script (Windows PowerShell)
$ErrorActionPreference = 'Stop'

# Check for Python 3.9+
if (-not (Get-Command python -ErrorAction SilentlyContinue)) {
    Write-Host 'Python 3 is required. Please install Python 3.9 or newer.'; exit 1
}
$pyver = python -c "import sys; print(f'{sys.version_info[0]}.{sys.version_info[1]}')"
if ([version]$pyver -lt [version]'3.9') {
    Write-Host "Python 3.9+ required. Found $pyver"; exit 1
}

# Create venv if not exists
if (-not (Test-Path '.venv')) {
    python -m venv .venv
}
. .\.venv\Scripts\Activate.ps1

# Upgrade pip
python -m pip install --upgrade pip

# Install requirements
if (Test-Path 'requirements.txt') {
    pip install -r requirements.txt
} else {
    Write-Host 'requirements.txt not found!'; exit 1
}

Write-Host "`nOpenChimera install complete!"
Write-Host "To activate your environment:"
Write-Host "  .\.venv\Scripts\Activate.ps1"
Write-Host "To run OpenChimera:"
Write-Host "  python run.py"
Write-Host "For onboarding, run:"
Write-Host "  python run.py onboard"
