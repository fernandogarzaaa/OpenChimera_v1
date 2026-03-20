param(
    [switch]$SkipNpmReinstall
)

$ErrorActionPreference = 'SilentlyContinue'

function Invoke-TaskkillByImageName {
    param([string]$ImageName)
    cmd /c "taskkill /F /IM $ImageName /T"
}

function Invoke-TaskkillByPort {
    param([int]$Port)
    $lines = netstat -ano | Select-String ":$Port\s"
    foreach ($line in $lines) {
        $parts = ($line.ToString() -replace '^\s+', '') -split '\s+'
        if ($parts.Length -ge 5 -and $parts[-1] -match '^\d+$') {
            $pid = [int]$parts[-1]
            if ($pid -gt 4) {
                cmd /c "taskkill /F /PID $pid /T"
            }
        }
    }
}

function Wait-ForHealth {
    param(
        [string]$Url,
        [int]$TimeoutSeconds = 30
    )

    $deadline = (Get-Date).AddSeconds($TimeoutSeconds)
    while ((Get-Date) -lt $deadline) {
        cmd /c "curl.exe --silent --show-error $Url" | Out-Null
        if ($LASTEXITCODE -eq 0) {
            return $true
        }
        Start-Sleep -Seconds 1
    }

    return $false
}

Write-Host "=== 1) Process Termination ==="
Invoke-TaskkillByImageName -ImageName "python.exe"
Invoke-TaskkillByImageName -ImageName "node.exe"
Invoke-TaskkillByImageName -ImageName "llama-server.exe"
Invoke-TaskkillByImageName -ImageName "ollama.exe"

foreach ($port in @(7870, 8080, 8081, 8082, 8083, 11434)) {
    Invoke-TaskkillByPort -Port $port
}

Write-Host "=== 2) Cache and Artifact Cleanup ==="
if (Test-Path "D:\openclaw\__pycache__") {
    Remove-Item -Path "D:\openclaw\__pycache__" -Recurse -Force
}

if (Test-Path "D:\appforge-main\__pycache__") {
    Remove-Item -Path "D:\appforge-main\__pycache__" -Recurse -Force
}

Get-ChildItem -Path "D:\openclaw" -Recurse -Filter *.pyc -File | Remove-Item -Force
Get-ChildItem -Path "D:\openclaw" -Recurse -Filter *sentinel*.json -File | Remove-Item -Force

Write-Host "=== 3) NPM Lock Artifact Cleanup ==="
Get-ChildItem -Path "C:\Users\ferna\AppData\Roaming\npm\node_modules" -Force |
    Where-Object { $_.Name -like ".openclaw-*" } |
    Remove-Item -Recurse -Force

Write-Host "=== 4) OpenClaw CLI Repair ==="
$openclawCmd = Get-Command openclaw -ErrorAction SilentlyContinue

if (-not $openclawCmd -or -not $SkipNpmReinstall) {
    cmd /c "npm i -g openclaw@latest --no-fund --no-audit --loglevel=error"
}

cmd /c "openclaw --version"

Write-Host "=== 5) Restart CHIMERA and Verify Health ==="
Push-Location "D:\openclaw"
try {
    .\start_chimera_ultimate.bat
} finally {
    Pop-Location
}

if (-not (Wait-ForHealth -Url "http://localhost:7870/health" -TimeoutSeconds 30)) {
    Write-Host "Warning: CHIMERA health endpoint did not become ready within 30 seconds."
}

Write-Host "HEALTH_CHECK_1"
curl.exe http://localhost:7870/health

Start-Sleep -Seconds 5
Write-Host "HEALTH_CHECK_2"
curl.exe http://localhost:7870/health

Write-Host "=== Recovery sequence complete ==="