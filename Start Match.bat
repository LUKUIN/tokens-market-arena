@echo off
chcp 936 >nul
cd /d "%~dp0"
title Tokens Trading Market - AI Edition - Spectator
setlocal

rem ==================================================================
rem Pinned runtime. GUI widgets and .pyc files are built against
rem Python 3.14, so do NOT look for another interpreter with
rem "where python" or "py -3.x". Change this one line on another PC.
rem ==================================================================
set "PY=C:\Users\User\AppData\Local\Programs\Python\Python314\python.exe"
if not exist "%PY%" (
    echo.
    echo   [ERROR] Pinned runtime not found:
    echo     %PY%
    echo   This build requires Python 3.14.7. Do not substitute another Python.
    echo.
    pause
    exit /b 1
)

rem ------------------------------------------------------------------
rem This edition never waits for keyboard input.
rem Everything is driven by environment variables; unset ones fall back
rem to the defaults below.
rem ------------------------------------------------------------------
if not defined TM_TRADER set "TM_TRADER=Guest"
if not defined TM_EVENTS set "TM_EVENTS=1"
if not defined TM_FR     set "TM_FR=0"
if not defined TM_SLOT   set "TM_SLOT=0"
if not defined TM_ASSIST set "TM_ASSIST=0"
if not defined TM_PORT   set "TM_PORT=8734"

echo.
echo   ==========================================
echo      Tokens Trading Market - AI Edition
echo   ==========================================
echo   Endpoint        http://127.0.0.1:%TM_PORT%
echo   Player          %TM_TRADER%
echo   Random events   %TM_EVENTS%
echo   Preferred Financing %TM_FR%  Slot Machine %TM_SLOT%  Outside Mercy %TM_ASSIST%
echo   The read-only spectator opens together with the server.
echo.
rem run.py seals the sources itself and restores them on exit. Do NOT start guard.py
rem here as well: a second seal encrypts whatever is in src/ at that moment, which is
rem already the decoy, and the real sources can never be restored from that vault.
"%PY%" run.py
echo.
echo   [EXITED] Server and spectator are closed.
pause
