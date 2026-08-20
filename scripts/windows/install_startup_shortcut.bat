@echo off
setlocal

rem Alternative to install_startup_task.bat for when Task Scheduler is
rem locked down (common on managed/work computers -- shows up as "ERROR:
rem Access is denied" from that script). This creates a shortcut in your
rem own Startup folder instead, which only needs permission to write to
rem your own user profile, not the system-wide Task Scheduler.

set SCRIPTDIR=%~dp0
set STARTUPDIR=%APPDATA%\Microsoft\Windows\Start Menu\Programs\Startup

powershell -NoProfile -Command "$q = [char]34; $ws = New-Object -ComObject WScript.Shell; $s = $ws.CreateShortcut('%STARTUPDIR%\Comment Insight Server.lnk'); $s.TargetPath = '%windir%\System32\wscript.exe'; $s.Arguments = $q + '%SCRIPTDIR%run_server_hidden.vbs' + $q; $s.WorkingDirectory = '%SCRIPTDIR%'; $s.Save()"

if %ERRORLEVEL% NEQ 0 (
    echo.
    echo Something went wrong creating the shortcut -- see the message above.
    pause
    exit /b 1
)

echo.
echo Done. Comment Insight will now start automatically, hidden in the
echo background, every time you log in to Windows.
echo.
echo Starting it now so you don't have to log out and back in...
wscript.exe "%SCRIPTDIR%run_server_hidden.vbs"
echo.
echo Give it a few seconds, then open http://127.0.0.1:8000 in your browser.
echo.
echo To stop it: run stop_server.bat
echo To remove the auto-start: run uninstall_startup_shortcut.bat
pause
