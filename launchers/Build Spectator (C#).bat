@echo off
setlocal
cd /d "%~dp0.."

echo Building Tokens spectator (C# / WPF)...
echo.
dotnet build viewer-cs\TokensWatch\TokensWatch.csproj -c Release --nologo
if errorlevel 1 (
  echo.
  echo Build failed. The .NET 8 SDK is required.
  pause
  exit /b 1
)

echo.
echo Done: viewer-cs\TokensWatch\bin\Release\net8.0-windows\TokensWatch.exe
pause
