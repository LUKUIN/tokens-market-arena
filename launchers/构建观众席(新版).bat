@echo off
chcp 936 >nul
setlocal
cd /d "%~dp0.."

echo.
echo   构建 C# 观众席（首次约 10-30 秒）
echo.

dotnet build viewer-cs\TokensWatch\TokensWatch.csproj -c Release --nologo
if errorlevel 1 (
    echo.
    echo   构建失败。请确认已安装 .NET 8 SDK。
    pause
    exit /b 1
)

echo.
echo   构建完成。双击 launchers\只开观众席^(新版^).bat 启动。
echo.
pause
