@echo off
if exist "%~dp0ready" (
  powershell.exe -NoProfile -ExecutionPolicy Bypass -File "%~dp0Check-Updates.ps1"
) else (
  powershell.exe -NoProfile -ExecutionPolicy Bypass -File "%~dp0Update-Vastgame.ps1"
)
pause
