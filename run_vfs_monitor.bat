@echo off
REM VFS Global (Netherlands / Tehran) Appointment Monitor - Task Scheduler entry point
REM Runs one check cycle. The monitor itself decides (from the state file) whether the
REM randomized interval has elapsed, so running this often is harmless.

cd /d "%~dp0"

REM Prefer the project virtual environment when it exists.
set "PYTHON=python"
if exist ".venv\Scripts\python.exe" set "PYTHON=.venv\Scripts\python.exe"

REM Check if Python is available
%PYTHON% --version >nul 2>&1
if errorlevel 1 (
    echo ERROR: Python is not installed or not in PATH
    pause
    exit /b 1
)

REM Check if dependencies are installed
%PYTHON% -c "import telegram, playwright" >nul 2>&1
if errorlevel 1 (
    echo Installing dependencies...
    %PYTHON% -m pip install -r requirements.txt
    %PYTHON% -m playwright install chromium
)

REM Run one check cycle (use "%PYTHON% monitor.py --scheduler" for continuous mode).
%PYTHON% monitor.py --once

if errorlevel 1 (
    echo.
    echo ERROR: Monitor run failed - see vfs_monitor.log
    pause
)
