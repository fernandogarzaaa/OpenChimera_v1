param(
    [switch]$SkipPreCommit,
    [string]$TestPattern = "test_*.py"
)

$ErrorActionPreference = "Stop"

$repoRoot = Split-Path -Parent $PSScriptRoot
Set-Location $repoRoot

if (-not $SkipPreCommit) {
    python -m pre_commit run --all-files
    if ($LASTEXITCODE -ne 0) {
        exit $LASTEXITCODE
    }
}

python run.py validate --pattern $TestPattern
exit $LASTEXITCODE