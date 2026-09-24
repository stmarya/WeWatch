@echo off
title Google Meet Admin App
echo ========================================================
echo   Launching Google Meet Admin (Monitoring Dashboard)
echo ========================================================

cd /d "%~dp0"

:: Check if port 5000 is listening
netstat -ano | findstr :5000 | findstr LISTENING >nul
if %errorlevel% neq 0 (
    echo [INFO] Starting WatcherSite Server on port 5000 (using venv)...
    if exist ".\venv\Scripts\python.exe" (
        start "" /b .\venv\Scripts\python.exe app.py
    ) else (
        start "" /b python app.py
    )
    timeout /t 5 /nobreak >nul
) else (
    echo [INFO] WatcherSite Server is already running.
)

:: Check if port 5001 is listening
netstat -ano | findstr :5001 | findstr LISTENING >nul
if %errorlevel% neq 0 (
    echo [INFO] Starting WebRTC Signaling Server on port 5001...
    if exist "%~dp0WebRTC_Meet" (
        pushd "%~dp0WebRTC_Meet"
    ) else (
        pushd "%~dp0..\WebRTC_Meet"
    )
    if exist "%~dp0venv\Scripts\python.exe" (
        start "" /b "%~dp0venv\Scripts\python.exe" app.py
    ) else if exist ".\venv\Scripts\python.exe" (
        start "" /b .\venv\Scripts\python.exe app.py
    ) else (
        start "" /b python app.py
    )
    popd
    timeout /t 2 /nobreak >nul
)

echo [INFO] Opening Google Meet Admin in Standalone App Mode...
start msedge --app=http://localhost:5000 --window-size=1366,768
exit
