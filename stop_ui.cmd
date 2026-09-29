@echo off
REM Double-click this file to stop the running web demo.
REM
REM Finds the process by PORT and verifies it is ours (health endpoint) before
REM killing it, so it will not touch other Python programs you may be running.
REM
REM ASCII-only on purpose: cmd.exe decodes .cmd files with the OEM code page.
setlocal
powershell -NoProfile -ExecutionPolicy Bypass -File "%~dp0stop_ui.ps1" %*
echo.
pause
endlocal
