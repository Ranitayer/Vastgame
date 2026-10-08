@echo off
set "VASTGAME_STREAM_FILE=%~dp0stream.json"
set "VASTGAME_STREAM_EDITOR=%~dp0Edit-Stream-Settings.ps1"
if exist "%LOCALAPPDATA%\Vastgame\ready" (
  set "VASTGAME_STREAM_FILE=%LOCALAPPDATA%\Vastgame\stream.json"
  set "VASTGAME_STREAM_EDITOR=%LOCALAPPDATA%\Vastgame\Edit-Stream-Settings.ps1"
)
powershell.exe -NoProfile -ExecutionPolicy Bypass -File "%VASTGAME_STREAM_EDITOR%" "%VASTGAME_STREAM_FILE%"
