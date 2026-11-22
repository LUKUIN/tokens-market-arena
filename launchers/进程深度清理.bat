@echo off
chcp 936 >nul
title 进程深度清理 - Tokens 交易市场
echo.
echo   ============================================================
echo     进程深度清理 - Tokens 交易市场
echo   ============================================================
echo.
echo   请先关闭对局，再清理遗留的运行时文件。历史战报会保留。
echo.
if /i "%~1"=="-y" goto SKIPPAUSE1
pause
:SKIPPAUSE1
powershell -NoProfile -ExecutionPolicy Bypass -File "%~dp0..\tools\deep-clean.ps1"
set "CLEANUP_STATUS=%ERRORLEVEL%"
echo.
if /i "%~1"=="-y" goto END
pause
:END
exit /b %CLEANUP_STATUS%
