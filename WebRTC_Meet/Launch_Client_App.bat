@echo off
title Google Meet Client App
echo ========================================================
echo   Launching Google Meet Client
echo ========================================================

cd /d "%~dp0"

:: Check if port 5001 is listening
netstat -ano | findstr :5001 | findstr LISTENING >nul
if %errorlevel% neq 0 (
    echo [INFO] Starting WebRTC Signaling Server on port 5001...
    start "" /b .\venv\Scripts\python.exe app.py
    timeout /t 3 /nobreak >nul
) else (
    echo [INFO] WebRTC Server is already running.
)

echo [INFO] Opening Google Meet Client in Standalone App Mode...
start msedge --app=http://localhost:5001 --window-size=1280,720
exit
