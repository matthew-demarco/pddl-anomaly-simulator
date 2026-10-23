@echo off
cd /d "%~dp0"

where py >nul 2>nul
if errorlevel 1 (
    echo Python was not found. Install Python 3 and enable the Python launcher.
    pause
    exit /b 1
)

py check_setup.py
if errorlevel 1 (
    pause
    exit /b 1
)

py main.py --problem p01 --plan plans\p01.plan --anomaly-id 1 --step-id 2 --anomaly-args l1 l3
pause
