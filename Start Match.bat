@echo off
chcp 936 >nul
cd /d "%~dp0"
title Tokens Trading Market - AI Edition - Spectator
setlocal

rem ==================================================================
rem Only Python 3.14 is accepted: GUI widgets and .pyc files are built
rem against it. The block below looks for it in order:
rem   1) the pinned install here   2) py -3.14   3) python on PATH (version checked)
rem ==================================================================
set "PY="
set "PYARGS="

rem ---------- locate Python 3.14, in order ----------
rem 1) the pinned install on this machine (fastest when present)
set "PY_PINNED=C:\Users\User\AppData\Local\Programs\Python\Python314\python.exe"
if exist "%PY_PINNED%" (
    set "PY=%PY_PINNED%"
    goto :py_ready
)
rem 2) the py launcher; -3.14 already pins the version
py -3.14 -c "import sys" >nul 2>&1
if not errorlevel 1 (
    set "PY=py"
    set "PYARGS=-3.14"
    goto :py_ready
)
rem 3) python on PATH, but only if it is 3.14
python -c "import sys; sys.exit(0 if sys.version_info[:2]==(3,14) else 1)" >nul 2>&1
if not errorlevel 1 (
    set "PY=python"
    goto :py_ready
)

echo.
echo   [ERROR] No Python 3.14 found.
echo     Looked for, in order:
echo       %PY_PINNED%
echo       py -3.14
echo       python on PATH
echo   Install Python 3.14.7 first. Other versions fail on .pyc and the GUI widgets.
echo.
pause
exit /b 1

:py_ready

rem ------------------------------------------------------------------
rem This edition never waits for keyboard input.
rem Everything is driven by environment variables; unset ones fall back
rem to the defaults below.
rem ------------------------------------------------------------------
if not defined TM_TRADER set "TM_TRADER=Guest"
if not defined TM_EVENTS set "TM_EVENTS=1"
if not defined TM_FR     set "TM_FR=1"
if not defined TM_SLOT   set "TM_SLOT=1"
if not defined TM_ASSIST set "TM_ASSIST=1"
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
echo   These three can only be set before the match starts.
echo.
rem run.py seals the sources itself and restores them on exit. Do NOT start guard.py
rem here as well: a second seal encrypts whatever is in src/ at that moment, which is
rem already the decoy, and the real sources can never be restored from that vault.
"%PY%" %PYARGS% run.py
echo.
echo   [EXITED] Server and spectator are closed.
pause
