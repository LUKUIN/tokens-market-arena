@echo off
setlocal
cd /d "%~dp0.."

if not defined TM_WATCH_API if defined TM_PORT set "TM_WATCH_API=http://127.0.0.1:%TM_PORT%"
set "EXE=viewer-cs\TokensWatch\bin\Release\net8.0-windows\TokensWatch.exe"

if not exist "%EXE%" (
  echo Not built yet. Run "Build Spectator (C#).bat" first.
  pause
  exit /b 1
)

start "" "%EXE%"
