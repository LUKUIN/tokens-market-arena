@echo off
chcp 936 >nul
setlocal
cd /d "%~dp0.."

if not defined TM_WATCH_API if defined TM_PORT set "TM_WATCH_API=http://127.0.0.1:%TM_PORT%"
set "EXE=viewer-cs\TokensWatch\bin\Release\net8.0-windows\TokensWatch.exe"
set "DIST=viewer-cs\dist\TokensWatch.exe"

if exist "%DIST%" (
    start "" "%DIST%"
    exit /b 0
)

if exist "%EXE%" (
    start "" "%EXE%"
    exit /b 0
)

echo.
echo   没有找到 TokensWatch.exe
echo.
echo   先构建一次：
echo     launchers\构建观众席^(新版^).bat
echo   或手动：
echo     dotnet build viewer-cs\TokensWatch -c Release
echo.
pause
exit /b 1
