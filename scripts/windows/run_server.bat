@echo off
setlocal

rem Runs the Comment Insight server and keeps it running -- if uvicorn ever
rem crashes, this restarts it a few seconds later instead of just stopping.
rem Meant to be launched hidden (see run_server_hidden.vbs), not double-clicked
rem directly, though double-clicking it works too -- you'll just see the window.

cd /d "%~dp0..\.."
if not exist data mkdir data

if not exist ".venv\Scripts\activate.bat" (
    echo [%date% %time%] ERROR: .venv not found. Run the first-time setup steps in README.md first. >> data\server.log
    exit /b 1
)

call .venv\Scripts\activate.bat

:loop
echo [%date% %time%] Starting Comment Insight server... >> data\server.log
python -m uvicorn app.main:app --host 127.0.0.1 --port 8000 >> data\server.log 2>&1
echo [%date% %time%] Server stopped, restarting in 5 seconds... >> data\server.log
ping -n 6 127.0.0.1 > NUL
goto loop
