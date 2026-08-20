@echo off
setlocal

rem Removes the auto-start shortcut created by install_startup_shortcut.bat.
rem This does NOT stop a copy of the server that's already running --
rem run stop_server.bat for that.

set STARTUPDIR=%APPDATA%\Microsoft\Windows\Start Menu\Programs\Startup

del "%STARTUPDIR%\Comment Insight Server.lnk" 2>nul

echo.
echo Removed. Comment Insight will no longer start automatically at login.
echo If it's currently running, run stop_server.bat to stop it too.
pause
