@echo off
setlocal

rem Registers a Windows Task Scheduler task that starts Comment Insight
rem (hidden, in the background) every time you log in to Windows. Safe to
rem run more than once -- it just replaces the existing task.

set TASKNAME=Comment Insight Server
set VBSPATH=%~dp0run_server_hidden.vbs

schtasks /Create /TN "%TASKNAME%" /TR "wscript.exe \"%VBSPATH%\"" /SC ONLOGON /RL LIMITED /F

if %ERRORLEVEL% NEQ 0 (
    echo.
    echo Something went wrong registering the task -- see the message above.
    pause
    exit /b 1
)

echo.
echo Done. Comment Insight will now start automatically, hidden in the
echo background, every time you log in to Windows.
echo.
echo Starting it now so you don't have to log out and back in...
schtasks /Run /TN "%TASKNAME%"
echo.
echo Give it a few seconds, then open http://127.0.0.1:8000 in your browser.
echo.
echo To stop it: run stop_server.bat
echo To remove the auto-start: run uninstall_startup_task.bat
pause
