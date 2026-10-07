@echo off
if not exist "%~dp0ready" (
  powershell.exe -NoProfile -ExecutionPolicy Bypass -File "%~dp0Complete-Setup.ps1"
  if errorlevel 1 exit /b 1
)
if "%~1"=="" goto console
wsl.exe --distribution Vastgame --user vastgame --exec /home/vastgame/.local/bin/vastgame %*
exit /b %errorlevel%
:console
wsl.exe --distribution Vastgame --user vastgame --exec /home/vastgame/.local/bin/vastgame help
echo.
echo Commands: vastgame start GAME, vastgame connect, vastgame stop
cmd.exe /k "set PATH=%~dp0;%PATH%"
