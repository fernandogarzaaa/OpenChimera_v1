param(
    [string]$TaskName = "OpenChimera",
    [string]$RunAsUser,
    [switch]$VerboseLogs
)

$ErrorActionPreference = "Stop"

$repoRoot = Split-Path -Parent $PSScriptRoot
$startScript = Join-Path $PSScriptRoot "start-openchimera.ps1"

if (-not (Test-Path $startScript)) {
    throw "Start script not found: $startScript"
}

$scriptArgument = "-NoProfile -ExecutionPolicy Bypass -File `"$startScript`""
if ($VerboseLogs) {
    $scriptArgument += " -VerboseLogs"
}

$action = New-ScheduledTaskAction -Execute "powershell.exe" -Argument $scriptArgument
$trigger = New-ScheduledTaskTrigger -AtStartup
$settings = New-ScheduledTaskSettingsSet -AllowStartIfOnBatteries -DontStopIfGoingOnBatteries -MultipleInstances IgnoreNew -RestartCount 999 -RestartInterval (New-TimeSpan -Minutes 1)
$principal = if ($RunAsUser) {
    New-ScheduledTaskPrincipal -UserId $RunAsUser -LogonType InteractiveOrPassword -RunLevel Highest
} else {
    New-ScheduledTaskPrincipal -UserId "SYSTEM" -LogonType ServiceAccount -RunLevel Highest
}

$task = New-ScheduledTask -Action $action -Trigger $trigger -Settings $settings -Principal $principal
Register-ScheduledTask -TaskName $TaskName -InputObject $task -Force | Out-Null

Write-Output "Registered scheduled task '$TaskName' for OpenChimera startup."
Write-Output "Repo root: $repoRoot"
Write-Output "Launcher: $startScript"
Write-Output "Use scripts\\remove-openchimera-task.ps1 to uninstall it."