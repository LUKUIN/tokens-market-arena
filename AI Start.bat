@echo off
chcp 936 >nul
cd /d "%~dp0"
rem ==================================================================
rem Unattended entry point (for scripts / agents).
rem v1.2.13: no duplicate lookup and launch logic any more - it delegates to
rem Start Match.bat:
rem   TM_NO_CONFIRM=1  skip the 5-second mis-click guard
rem   TM_IDLE_ABORT=0  keep the idle abort off
rem                    (an agent thinking for a while is not "nobody acting")
rem So the launch path has a single source of truth.
rem ==================================================================
setlocal
set "TM_NO_CONFIRM=1"
if not defined TM_IDLE_ABORT set "TM_IDLE_ABORT=0"

call "%~dp0Start Match.bat" %*
goto :eof
