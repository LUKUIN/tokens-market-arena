@echo off
chcp 936 >nul
cd /d "%~dp0"
title Tokens Trading Market - Spectator only
setlocal

rem ==================================================================
rem Pinned runtime: Python 3.14 only.
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
rem Opens ONLY the read-only spectator window.
rem
rem A normal start already opens the spectator; this is a recovery entry
rem for "I closed the window by accident and the match is still running".
rem
rem If a match already answers on the port, this attaches to it and does
rem nothing else: no server, no guard, no sealing. Attaching must never
rem touch the sources, or it would re-seal decoys over a live vault.
rem If nothing is running, it starts a server first so you can still watch.
rem
rem Closing this window does NOT end the match. Use /quit, or the
rem "End processes" button in the window, to settle it.
rem ------------------------------------------------------------------
if not defined TM_PORT set "TM_PORT=8734"

echo.
echo   ==========================================
echo      Tokens Trading Market - Spectator
echo   ==========================================
echo   Port           %TM_PORT%
echo   Read-only      no orders, no fast-forward
echo.

"%PY%" run.py spectator 127.0.0.1 %TM_PORT%

echo.
echo   [EXITED] Spectator closed. The match itself was not affected.
pause
