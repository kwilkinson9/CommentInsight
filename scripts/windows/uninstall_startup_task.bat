@echo off
setlocal

rem Removes the auto-start task created by install_startup_task.bat.
rem This does NOT stop a copy of the server that's already running --
rem run stop_server.bat for that.

set TASKNAME=Comment Insight Server

schtasks /Delete /TN "%TASKNAME%" /F

echo.
echo Removed. Comment Insight will no longer start automatically at login.
echo If it's currently running, run stop_server.bat to stop it too.
pause
