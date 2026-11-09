@echo off
chcp 936 >nul
cd /d "%~dp0.."
if defined TM_NO_CONFIRM (title Tokens Trading Market - AI Edition - Unattended) else (title Tokens Trading Market - AI Edition - Spectator)
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
if not defined TM_IDLE_ABORT set "TM_IDLE_ABORT=12"
set "IDLE_WARN=%TM_IDLE_ABORT%"
if "%IDLE_WARN%"=="0" set "IDLE_WARN=disabled"

echo.
echo   ==========================================
echo      Tokens Trading Market - AI Edition
echo   ==========================================
echo   Endpoint        http://127.0.0.1:%TM_PORT%
echo   Player          %TM_TRADER%
echo   Random events   %TM_EVENTS%
echo   Preferred Financing %TM_FR%  Slot Machine %TM_SLOT%  Outside Mercy %TM_ASSIST%
echo   Press Y within 5 seconds to start; otherwise it cleans up and exits.
echo   To have an AI contest: run python run.py in the repo root (this window already cds there)
echo.
echo   !! AI contestant edition: the GUI is read-only, no order / close / fast-forward buttons.
echo   !! Humans should use TokensMarket-OpenSource-Human instead.
echo   !! Started with python run.py, the match settles itself after %IDLE_WARN% idle minutes
echo   !! (TM_IDLE_ABORT).

rem ==================================================================
rem v1.2.12 adds a mis-click guard while keeping the real launcher path.
rem   - human double-click (console stdin): waits 5 s, then cleans up and exits
rem   - script / agent call (no console stdin): choice returns 255, starts normally
rem So an accidental click cannot burn 45 idle minutes, and a real agent is not killed.
rem ==================================================================
echo.
rem v1.2.13: the unattended entry (AI Start.bat) sets TM_NO_CONFIRM=1 and skips
rem this prompt. The launcher logic exists in exactly one place now.
if defined TM_NO_CONFIRM goto :direct_start

echo   Press Y within 5 seconds to start (only if an agent will connect).
echo   Otherwise it cleans up and exits.
choice /c YN /t 5 /d N /n /m " " 2>nul
if errorlevel 255 goto :direct_start
if errorlevel 2 goto :abort_start

:direct_start

rem run.py seals the sources itself and restores them on exit. Do NOT start guard.py here.
"%PY%" %PYARGS% run.py
echo.
echo   [EXITED] Server and spectator are closed.
if not defined TM_NO_CONFIRM pause
goto :eof

:abort_start
echo.
echo   Cancelled. Stopping leftover processes and temporary files...
powershell -NoProfile -ExecutionPolicy Bypass -File "%~dp0..\tools\deep-clean.ps1"
echo.
echo   [CLEANED]
echo   - AI contest: run  python run.py  in the repo root
echo   - Humans: use TokensMarket-OpenSource-Human
echo.
pause
goto :eof
