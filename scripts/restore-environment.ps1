# D: Drive Environment Restore Script
# Run this AFTER reinstalling Node.js, Python, Git, and CUDA to D: drive

Write-Host "============================================" -ForegroundColor Cyan
Write-Host "  D: Drive Environment Restore" -ForegroundColor Cyan
Write-Host "============================================" -ForegroundColor Cyan
Write-Host ""

$ErrorActionPreference = "Continue"

# Restore OpenClaw config
Write-Host "[1/5] Restoring OpenClaw config..." -ForegroundColor Yellow
if (Test-Path "D:\openclaw\backup\openclaw-config\") {
    Copy-Item "D:\openclaw\backup\openclaw-config\" "$env:USERPROFILE\.openclaw\" -Recurse -Force
    Write-Host "  ✅ OpenClaw config restored" -ForegroundColor Green
} else {
    Write-Host "  ⚠️  Backup not found, skipping..." -ForegroundColor Red
}

# Verify and setup Node.js
Write-Host ""
Write-Host "[2/5] Checking Node.js..." -ForegroundColor Yellow
if (Test-Path "D:\Program Files\nodejs\node.exe") {
    $nodeVersion = & "D:\Program Files\nodejs\node.exe" --version
    Write-Host "  ✅ Node.js $nodeVersion found" -ForegroundColor Green
    
    Write-Host "  Installing global npm packages..." -ForegroundColor Gray
    & "D:\Program Files\nodejs\npm.exe" install -g openclaw clawhub
} else {
    Write-Host "  ⚠️  Node.js not found at D:\Program Files\nodejs\" -ForegroundColor Red
    Write-Host "     Please reinstall Node.js to D:\Program Files\nodejs\" -ForegroundColor Red
}

# Verify and setup Python
Write-Host ""
Write-Host "[3/5] Checking Python..." -ForegroundColor Yellow
if (Test-Path "D:\Program Files\Python314\python.exe") {
    $pythonVersion = & "D:\Program Files\Python314\python.exe" --version
    Write-Host "  ✅ $pythonVersion found" -ForegroundColor Green
    
    if (Test-Path "D:\openclaw\backup\pip-requirements.txt") {
        Write-Host "  Installing Python packages..." -ForegroundColor Gray
        & "D:\Program Files\Python314\python.exe" -m pip install -r "D:\openclaw\backup\pip-requirements.txt"
    }
} else {
    Write-Host "  ⚠️  Python not found at D:\Program Files\Python314\" -ForegroundColor Red
    Write-Host "     Please reinstall Python to D:\Program Files\Python314\" -ForegroundColor Red
}

# Verify Git
Write-Host ""
Write-Host "[4/5] Checking Git..." -ForegroundColor Yellow
if (Test-Path "D:\Program Files\Git\cmd\git.exe") {
    $gitVersion = & "D:\Program Files\Git\cmd\git.exe" --version
    Write-Host "  ✅ $gitVersion found" -ForegroundColor Green
} else {
    Write-Host "  ⚠️  Git not found at D:\Program Files\Git\" -ForegroundColor Red
}

# Verify CUDA
Write-Host ""
Write-Host "[5/5] Checking CUDA..." -ForegroundColor Yellow
if (Test-Path "D:\NVIDIA\CUDA\v13.1\bin\nvcc.exe") {
    $cudaVersion = & "D:\NVIDIA\CUDA\v13.1\bin\nvcc.exe" --version | Select-String "release" | Select-Object -First 1
    Write-Host "  ✅ CUDA found - $cudaVersion" -ForegroundColor Green
} else {
    Write-Host "  ⚠️  CUDA not found at D:\NVIDIA\CUDA\v13.1\" -ForegroundColor Red
    Write-Host "     GPU acceleration won't work without CUDA" -ForegroundColor Red
}

Write-Host ""
Write-Host "============================================" -ForegroundColor Cyan
Write-Host "  Restore Complete!" -ForegroundColor Green
Write-Host "============================================" -ForegroundColor Cyan
Write-Host ""
Write-Host "Next steps:" -ForegroundColor Yellow
Write-Host "1. Verify PATH includes D:\Program Files\nodejs\" -ForegroundColor Gray
Write-Host "2. Verify PATH includes D:\Program Files\Python314\" -ForegroundColor Gray
Write-Host "3. Verify PATH includes D:\Program Files\Python314\Scripts\" -ForegroundColor Gray
Write-Host "4. Verify PATH includes D:\NVIDIA\CUDA\v13.1\bin\" -ForegroundColor Gray
Write-Host "5. Run: openclaw gateway status" -ForegroundColor Gray
Write-Host ""
