@echo off
if /i "%~1"=="update" goto update
if not exist "%~dp0ready" (
  powershell.exe -NoProfile -ExecutionPolicy Bypass -File "%~dp0Install-Vastgame.ps1"
  if errorlevel 1 exit /b 1
  if not exist "%LOCALAPPDATA%\Vastgame\ready" exit /b 0
)
if "%~1"=="" goto console
wsl.exe --distribution Vastgame --user vastgame --exec /home/vastgame/.local/bin/vastgame %*
exit /b %errorlevel%
:console
wsl.exe --distribution Vastgame --user vastgame --exec /home/vastgame/.local/bin/vastgame help
cmd.exe /k "set PATH=%~dp0;%PATH%"

exit /b %errorlevel%
:update
powershell.exe -NoProfile -ExecutionPolicy Bypass -File "%~dp0Check-Updates.ps1"
exit /b %errorlevel%
