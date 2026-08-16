@echo off
setlocal

rem Stops a running Comment Insight server, whether it was started hidden
rem (via the scheduled task) or in a visible window. Only targets the
rem specific python process running our uvicorn command -- won't touch any
rem other Python programs you have running.

powershell -NoProfile -Command "$stopped = $false; Get-CimInstance Win32_Process | Where-Object { $_.Name -eq 'python.exe' -and $_.CommandLine -like '*uvicorn*app.main:app*' } | ForEach-Object { Stop-Process -Id $_.ProcessId -Force; $stopped = $true }; if ($stopped) { Write-Host 'Comment Insight server stopped.' } else { Write-Host 'Comment Insight server was not running.' }"

pause
