# Publishes this folder to a GitHub repository and starts the free GitHub Actions
# monitor (no server needed, and GitHub's machines are outside the Netherlands).
#
# BEFORE RUNNING, sign in once (a browser window opens):
#     gh auth login
#
# Then:  right-click this file -> Run with PowerShell
#        (or: powershell -ExecutionPolicy Bypass -File .\publish_to_github.ps1)
#
# Note on visibility: the workflow needs unlimited minutes, which GitHub gives to
# PUBLIC repositories. Nothing secret is stored in the repository - your Telegram
# values are put into GitHub Secrets (masked in logs). Use -Private if you prefer,
# but then keep in mind the free minute budget (2000/month) and lower the frequency.

param(
    [string]$RepoName = 'vfs-tehran-appointment-monitor',
    [switch]$Private
)

$ErrorActionPreference = 'Stop'
$projectDir = Split-Path -Parent $MyInvocation.MyCommand.Path

Write-Host ""
Write-Host "======================================================================"
Write-Host " Publish to GitHub and start the free monitor"
Write-Host "======================================================================"

$null = gh auth status 2>&1
if ($LASTEXITCODE -ne 0) {
    throw "Not signed in to GitHub yet. Run this first:  gh auth login"
}

$envFile = Join-Path $projectDir '.env'
if (-not (Test-Path $envFile)) {
    throw ".env was not found next to this script: $envFile"
}

$settings = @{}
Get-Content $envFile | Where-Object { $_ -match '^\s*[A-Z_]+\s*=' } | ForEach-Object {
    $parts = $_.Split('=', 2)
    $settings[$parts[0].Trim()] = $parts[1].Trim()
}

Push-Location $projectDir
try {
    if (-not (Test-Path (Join-Path $projectDir '.git'))) {
        Write-Host "1) Creating the local git repository ..."
        git init | Out-Null
        git -c core.autocrlf=false add -A
        git -c user.name='amir12358' -c user.email='amir12358@gmail.com' commit -m 'VFS Tehran appointment monitor' | Out-Null
    } else {
        Write-Host "1) Local git repository already exists ..."
    }

    $visibility = if ($Private) { '--private' } else { '--public' }
    Write-Host "2) Creating the GitHub repository and pushing ..."
    gh repo create $RepoName $visibility --source=. --remote=origin --push

    Write-Host "3) Storing the Telegram values as repository secrets ..."
    foreach ($key in @('TELEGRAM_BOT_TOKEN', 'TELEGRAM_CHAT_ID', 'TELEGRAM_STATUS_CHAT_ID', 'TELEGRAM_ALERT_CHAT_ID')) {
        if ($settings.ContainsKey($key) -and $settings[$key]) {
            $settings[$key] | gh secret set $key
            Write-Host "   secret set: $key"
        } else {
            Write-Warning "   missing value in .env: $key"
        }
    }

    Write-Host "4) Starting the first run (this answers whether GitHub's IP is accepted) ..."
    gh workflow run vfs-monitor.yml
    Start-Sleep -Seconds 8
    gh run list --limit 3
}
finally {
    Pop-Location
}

Write-Host ""
Write-Host "======================================================================"
Write-Host " Done. To watch the current run:   gh run watch"
Write-Host " To read the last log:             gh run view --log"
Write-Host " To run it again by hand:          gh workflow run vfs-monitor.yml"
Write-Host " The workflow also runs every 15 minutes on its own."
Write-Host "======================================================================"
Write-Host ""
Read-Host "Press Enter to close"
