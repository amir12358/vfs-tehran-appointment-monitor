# Copies this project to your Oracle server and starts the installer there.
#
# HOW TO RUN (from this project folder):
#   Right-click this file -> "Run with PowerShell"
#   (If Windows blocks it, open PowerShell in this folder and type:
#        powershell -ExecutionPolicy Bypass -File .\upload_to_server.ps1 )
#
# You will be asked for:
#   - the server's public IP address (Oracle shows it on the instance page)
#   - the path to your private key file (the .key file Oracle made you download)
#
# Your own PC does NOT need to be able to open the appointment website. Only the
# server matters.

param(
    [string]$ServerIp,
    [string]$KeyFile,
    [string]$UserName = 'ubuntu'
)

$ErrorActionPreference = 'Stop'

$projectDir = Split-Path -Parent $MyInvocation.MyCommand.Path
$parentDir = Split-Path -Parent $projectDir
$folderName = Split-Path -Leaf $projectDir
$remoteDir = "~/$folderName"

Write-Host ""
Write-Host "======================================================================"
Write-Host " Upload VFS monitor to your Oracle server"
Write-Host "======================================================================"

if (-not $ServerIp) {
    $ServerIp = Read-Host "Server public IP address (e.g. 130.61.12.34)"
}
if (-not $KeyFile) {
    $KeyFile = Read-Host "Full path to your private key file (e.g. C:\Users\You\Downloads\ssh-key-2026-09-21.key)"
}

if (-not (Test-Path $KeyFile)) {
    throw "Key file not found: $KeyFile"
}

$target = "$UserName@$ServerIp"
$archive = Join-Path $env:TEMP 'vfs_monitor_upload.tar.gz'
if (Test-Path $archive) { Remove-Item $archive -Force }

Write-Host ""
Write-Host "1) Building the upload package ..."
# The Linux scripts must not carry Windows line endings, otherwise bash on the
# server fails with "$'\r': command not found".
Get-ChildItem (Join-Path $projectDir 'deploy\*.sh') -ErrorAction SilentlyContinue | ForEach-Object {
    $text = [IO.File]::ReadAllText($_.FullName) -replace "`r`n", "`n"
    [IO.File]::WriteAllText($_.FullName, $text)
    Write-Host "   normalised line endings: $($_.Name)"
}
Push-Location $parentDir
try {
    tar -czf $archive `
        --exclude='.venv' `
        --exclude='.browser_profile' `
        --exclude='recon_out' `
        --exclude='__pycache__' `
        --exclude='.pytest_cache' `
        --exclude='vfs_monitor.log' `
        --exclude='vfs_monitor.lock' `
        --exclude='vfs_state.json' `
        --exclude='test_state_*.json' `
        $folderName
}
finally {
    Pop-Location
}
Write-Host "   package ready: $archive"

Write-Host ""
Write-Host "2) Testing the connection (the first time you will be asked to accept the server's fingerprint - type yes) ..."
ssh -i $KeyFile -o StrictHostKeyChecking=accept-new $target "echo connected as `$(whoami) on `$(hostname)"

Write-Host ""
Write-Host "3) Uploading ..."
scp -i $KeyFile $archive "${target}:~/vfs_monitor_upload.tar.gz"

Write-Host ""
Write-Host "4) Unpacking and installing on the server (takes a few minutes) ..."
ssh -i $KeyFile $target "mkdir -p $remoteDir && tar -xzf ~/vfs_monitor_upload.tar.gz -C $remoteDir --strip-components=1 && chmod +x $remoteDir/deploy/install_server.sh && $remoteDir/deploy/install_server.sh"

Write-Host ""
Write-Host "======================================================================"
Write-Host " Finished. Check the output above for the verdict of the test check."
Write-Host "======================================================================"
Write-Host ""
Read-Host "Press Enter to close"
