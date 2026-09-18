@echo off
cd /d "%~dp0"

where py >nul 2>nul
if errorlevel 1 (
    echo Python was not found. Install Python 3 and enable the Python launcher.
    pause
    exit /b 1
)

py main.py --problem p01 --plan plans\p01.plan
pause
