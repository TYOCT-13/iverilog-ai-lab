@echo off
REM Double-click this file to launch the web demo.
REM
REM Why a .cmd shim: the default Windows PowerShell execution policy blocks .ps1
REM files, so double-clicking one usually just flashes a window. Passing
REM -ExecutionPolicy Bypass here keeps that from becoming a step the user has to
REM learn -- it is the script's problem, not theirs.
REM
REM This file is deliberately ASCII-only: cmd.exe decodes .cmd files using the
REM OEM code page, so non-ASCII text here would print as mojibake. All Chinese
REM messages come from start_ui.ps1, which is UTF-8 with a BOM.
setlocal
powershell -NoProfile -ExecutionPolicy Bypass -File "%~dp0start_ui.ps1" %*
if errorlevel 1 (
  echo.
  echo Launch failed with exit code %errorlevel%. See the messages above.
  pause
)
endlocal
