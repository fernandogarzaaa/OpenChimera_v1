[CmdletBinding(SupportsShouldProcess)]
param(
    [switch]$VerboseLogs
)

$ErrorActionPreference = "Stop"

$repoRoot = Split-Path -Parent $PSScriptRoot
$pythonPath = Join-Path $repoRoot ".venv\Scripts\python.exe"
$runPath = Join-Path $repoRoot "run.py"
$logsDir = Join-Path $repoRoot "logs"
$logPath = Join-Path $logsDir "openchimera-task.log"

if (-not (Test-Path $pythonPath)) {
    throw "OpenChimera virtual environment python was not found at $pythonPath"
}

if (-not (Test-Path $runPath)) {
    throw "OpenChimera entrypoint was not found at $runPath"
}

New-Item -ItemType Directory -Path $logsDir -Force | Out-Null
Set-Location $repoRoot

$arguments = @($runPath, "serve")
if ($VerboseLogs) {
    $arguments += "--verbose"
}

"[$([DateTime]::UtcNow.ToString('o'))] Starting OpenChimera task process" | Out-File -FilePath $logPath -Append -Encoding utf8
if (-not $PSCmdlet.ShouldProcess($repoRoot, "Start OpenChimera runtime")) {
    Write-Output "Would start OpenChimera from $repoRoot using $pythonPath"
    exit 0
}
& $pythonPath @arguments *>> $logPath
$exitCode = $LASTEXITCODE
"[$([DateTime]::UtcNow.ToString('o'))] OpenChimera task process exited with code $exitCode" | Out-File -FilePath $logPath -Append -Encoding utf8
exit $exitCode