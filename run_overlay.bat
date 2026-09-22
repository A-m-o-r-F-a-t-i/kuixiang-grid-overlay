@echo off
setlocal
cd /d "%~dp0"
PowerShell.exe -NoProfile -ExecutionPolicy Bypass -File "%~dp0start_overlay.ps1"
set "RESULT=%ERRORLEVEL%"
endlocal & exit /b %RESULT%
