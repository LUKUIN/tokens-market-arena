@echo off
chcp 936 >nul
cd /d "%~dp0"
title Tokens Trading Market - Spectator only
where python >nul 2>nul
if errorlevel 1 (
    echo.
    echo   [ERROR] python command not found.
    echo   Install Python 3.10 or newer and tick "Add python.exe to PATH" during setup.
    echo.
    pause
    exit /b 1
)

rem ------------------------------------------------------------------
rem Opens ONLY the read-only spectator window.
rem
rem Use it when the match is already running but no window appeared:
rem   - an agent started the game with "python run.py server"
rem   - the Tk window failed to open, or was closed by accident
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

python run.py spectator 127.0.0.1 %TM_PORT%

echo.
echo   [EXITED] Spectator closed. The match itself was not affected.
pause
