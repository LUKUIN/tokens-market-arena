@echo off
chcp 936 >nul
cd /d "%~dp0.."
title Tokens Trading Market - Spectator only
setlocal

rem ==================================================================
rem Pinned runtime: Python 3.14 only.
rem ==================================================================
set "PY="
set "PYARGS="

rem ---------- locate Python 3.14, in order ----------
rem 1) the pinned install on this machine (fastest when present)
set "PY_PINNED=%LOCALAPPDATA%\Programs\Python\Python314\python.exe"
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

"%PY%" %PYARGS% run.py spectator 127.0.0.1 %TM_PORT%

echo.
echo   [EXITED] Spectator closed. The match itself was not affected.
pause

rem Only Python 3.14 is accepted; try the pinned install, then py -3.14, then python on PATH.