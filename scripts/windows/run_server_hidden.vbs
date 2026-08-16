' Launches run_server.bat completely hidden -- no console window at all.
' Used by the scheduled task installed via install_startup_task.bat.

Dim objShell, scriptDir
Set objShell = CreateObject("WScript.Shell")
scriptDir = Left(WScript.ScriptFullName, InStrRev(WScript.ScriptFullName, "\"))
objShell.Run """" & scriptDir & "run_server.bat""", 0, False
