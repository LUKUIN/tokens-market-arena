@echo off
chcp 936 >nul
title Deep process cleanup - Tokens Trading Market
echo.
echo   ============================================================
echo     Deep process cleanup - Tokens Trading Market
echo   ============================================================
echo.
echo   Remove stale runtime files after the match has stopped.
echo   Historical reports are kept.
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
