@echo off
chcp 936 >nul
cd /d "%~dp0"
title Tokens Trading Market - AI Edition - Spectator
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
rem This edition never waits for keyboard input.
rem Everything is driven by environment variables; unset ones fall back
rem to the defaults below. Set them before double-clicking, or launch
rem via run.py / a harness and pass them in the environment.
rem ------------------------------------------------------------------
if not defined TM_TRADER set "TM_TRADER=Guest"
if not defined TM_EVENTS set "TM_EVENTS=1"
if not defined TM_FR     set "TM_FR=0"
if not defined TM_SLOT   set "TM_SLOT=0"

echo.
echo   ==========================================
echo      Tokens Trading Market - AI Edition
echo   ==========================================
echo   Endpoint        http://127.0.0.1:8734
echo   Player          %TM_TRADER%
echo   Random events   %TM_EVENTS%
echo   Finance Reversal %TM_FR%    Slot Machine %TM_SLOT%
echo   GUI is a read-only spectator; there is no investment panel.
echo.
if not defined TM_PORT set "TM_PORT=8734"
rem run.py seals the sources itself and restores them on exit. Do NOT start guard.py
rem here as well: a second seal encrypts whatever is in src/ at that moment, which is
rem already the decoy, and the real sources can never be restored from that vault.
python run.py
echo.
echo   [EXITED] Server and spectator are closed.
pause
