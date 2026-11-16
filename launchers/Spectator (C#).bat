@echo off
setlocal
cd /d "%~dp0.."

set "EXE=viewer-cs\TokensWatch\bin\Release\net8.0-windows\TokensWatch.exe"

if not exist "%EXE%" (
  echo Not built yet. Run "Build Spectator (C#).bat" first.
  pause
  exit /b 1
)

start "" "%EXE%"
