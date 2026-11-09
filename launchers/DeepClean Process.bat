@echo off
chcp 936 >nul
title Deep process cleanup - Tokens Trading Market
echo.
echo   ============================================================
echo     Deep process cleanup - Tokens Trading Market
echo   ============================================================
echo.
echo   Kills every leftover game process (matched by command line and by port),
echo   and removes runtime files plus the _agent directory under data.
echo   Historical reports in the reports subdirectory are never touched.
echo.
echo   When to use: right after a reset, before starting the next match.
echo.
if /i "%~1"=="-y" goto SKIPPAUSE1
pause
:SKIPPAUSE1
powershell -NoProfile -ExecutionPolicy Bypass -File "%~dp0..\tools\deep-clean.ps1"
echo.
if /i "%~1"=="-y" goto END
pause
:END
