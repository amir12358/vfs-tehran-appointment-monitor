# Registers a Windows Task Scheduler entry that runs the VFS monitor every 30 minutes.
# The monitor skips cycles until its own randomized interval (1200-2400 s) has elapsed,
# so 30-minute triggers are cheap and never overlap.
#
# Usage (PowerShell, no admin needed for a per-user task):
#   .\register_task.ps1
#   .\register_task.ps1 -IntervalMinutes 60
#   .\register_task.ps1 -Remove

param(
    [int]$IntervalMinutes = 30,
    [switch]$Remove
)

$ErrorActionPreference = 'Stop'
$taskName = 'VFS Global Tehran Appointment Monitor'
$projectDir = Split-Path -Parent $MyInvocation.MyCommand.Path
$launcher = Join-Path $projectDir 'run_vfs_monitor.bat'

if ($Remove) {
    schtasks /Delete /TN $taskName /F
    Write-Host "Removed scheduled task '$taskName'."
    return
}

if (-not (Test-Path $launcher)) {
    throw "run_vfs_monitor.bat was not found next to this script: $launcher"
}

schtasks /Create /TN $taskName /TR "`"$launcher`"" /SC MINUTE /MO $IntervalMinutes /F

Write-Host ""
Write-Host "Registered '$taskName' to run every $IntervalMinutes minutes."
Write-Host "Inspect: schtasks /Query /TN `"$taskName`" /V /FO LIST"
Write-Host "Run now: schtasks /Run    /TN `"$taskName`""
Write-Host "Remove : .\register_task.ps1 -Remove"
