@echo off
REM ============================================================
REM  VFS Tehran monitor - one-click setup and first test
REM
REM  Double-click this file ON THE IRAN COMPUTER.
REM  It installs everything it needs, then looks at the website
REM  and saves what it saw into the recon_out folder.
REM ============================================================
title VFS Tehran monitor - setup and first check
cd /d "%~dp0"

echo.
echo ============================================================
echo  Step 1 of 4  -  checking Python
echo ============================================================
python --version
if errorlevel 1 (
    echo.
    echo Python is not installed on this computer.
    echo Get it from https://www.python.org/downloads/
    echo IMPORTANT: on the first screen tick "Add python.exe to PATH".
    echo.
    pause
    exit /b 1
)

echo.
echo ============================================================
echo  Step 2 of 4  -  preparing its own private workspace
echo ============================================================
if not exist ".venv\Scripts\python.exe" python -m venv .venv
if errorlevel 1 goto :failed

echo.
echo ============================================================
echo  Step 3 of 4  -  installing the needed pieces
echo  (this takes a few minutes the first time)
echo ============================================================
".venv\Scripts\python.exe" -m pip install --upgrade pip
".venv\Scripts\python.exe" -m pip install -r requirements.txt
if errorlevel 1 goto :failed
".venv\Scripts\python.exe" -m playwright install chromium
if errorlevel 1 goto :failed

echo.
echo ============================================================
echo  Step 4 of 4  -  looking at the website (about 1 minute)
echo ============================================================
if not exist "recon_out" mkdir recon_out
".venv\Scripts\python.exe" recon_vfs.py > "recon_out\report.txt" 2>&1
type "recon_out\report.txt"

echo.
echo ============================================================
echo  DONE.
echo  Please send these two files to your helper:
echo    recon_out\report.txt
echo    the newest vfs_xxxx.txt inside recon_out
echo ============================================================
start "" "%~dp0recon_out"
echo.
pause
exit /b 0

:failed
echo.
echo ============================================================
echo  Something went wrong. Copy the text in this window and
echo  send it to your helper.
echo ============================================================
pause
exit /b 1
