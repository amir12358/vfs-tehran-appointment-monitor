@echo off
REM ============================================================
REM  VFS Tehran monitor - Telegram setup (double-click me)
REM
REM  Asks for your bot token and chat ID, saves them, and sends
REM  one test message so you know it works.
REM ============================================================
title VFS Tehran monitor - Telegram setup
cd /d "%~dp0"

set "PYTHON=python"
if exist ".venv\Scripts\python.exe" set "PYTHON=.venv\Scripts\python.exe"

echo.
echo ============================================================
echo  Telegram setup
echo ============================================================
echo  You need two things (see START_HERE.md, Part 2):
echo    1. the bot token from @BotFather  (looks like 123456789:AAH...)
echo    2. your chat ID (a number, e.g. 36010309)
echo.

if exist ".env" (
    echo  A .env file already exists and will be replaced.
    echo.
)

set "TOKEN="
set "CHATID="
set /p "TOKEN=Paste the bot token and press Enter: "
echo.
set /p "CHATID=Paste the chat ID and press Enter: "
echo.

if "%TOKEN%"=="" goto :missing
if "%CHATID%"=="" goto :missing

> ".env" echo TELEGRAM_BOT_TOKEN=%TOKEN%
>> ".env" echo TELEGRAM_CHAT_ID=%CHATID%
>> ".env" echo TELEGRAM_STATUS_CHAT_ID=%CHATID%
>> ".env" echo TELEGRAM_ALERT_CHAT_ID=%CHATID%
>> ".env" echo SITE_NAME=VFS Global Netherlands - Tehran
>> ".env" echo TASK_SCHEDULER_MODE=True

echo Saved. Sending a test message now...
echo.
"%PYTHON%" test_appointment_change.py --send

echo.
echo If you received the messages on Telegram, setup is complete.
echo If not: make sure you pressed /start in the chat with your own bot.
echo.
pause
exit /b 0

:missing
echo.
echo No token or no chat ID was entered - nothing was changed.
echo.
pause
exit /b 1
