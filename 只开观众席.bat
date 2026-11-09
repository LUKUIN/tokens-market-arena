@echo off
chcp 936 >nul
cd /d "%~dp0"
title Tokens 交易市场 - 只开观众席
setlocal

rem ==================================================================
rem 运行时只接受 Python 3.14；下面按顺序查找：本机固定路径 → py -3.14 → PATH 里的 python。
rem ==================================================================
set "PY="
set "PYARGS="

rem ---------- 按顺序找 Python 3.14 ----------
rem 1 本机固定路径（存在就用，最快）
set "PY_PINNED=C:\Users\User\AppData\Local\Programs\Python\Python314\python.exe"
if exist "%PY_PINNED%" (
    set "PY=%PY_PINNED%"
    goto :py_ready
)
rem 2 py 启动器：-3.14 已经把版本限定住
py -3.14 -c "import sys" >nul 2>&1
if not errorlevel 1 (
    set "PY=py"
    set "PYARGS=-3.14"
    goto :py_ready
)
rem 3 PATH 里的 python，且必须是 3.14
python -c "import sys; sys.exit(0 if sys.version_info[:2]==(3,14) else 1)" >nul 2>&1
if not errorlevel 1 (
    set "PY=python"
    goto :py_ready
)

echo.
echo   [错误] 没找到 Python 3.14。
echo     已依次查找：
echo       %PY_PINNED%
echo       py -3.14
echo       PATH 里的 python
echo   请先安装 Python 3.14.7；其他版本会因 .pyc 与界面控件不兼容而起不来。
echo.
pause
exit /b 1

:py_ready

rem ------------------------------------------------------------------
rem 只打开只读观众席窗口，不启动新的一局。
rem
rem 用在「窗口没弹出来，或者被误关了」的时候。
rem 正常启动本来就会带观众席，这个脚本是补救入口，不是常规入口。
rem
rem 如果端口上已经有一局在应答，本脚本只挂窗口，别的什么都不做：
rem 不起服务、不起守卫、不封存源码。挂载一旦去封存，就会把诱饵加密进新箱子，
rem 真源码再也还原不回来。
rem 如果端口上没有对局，它会先把服务起起来，保证你能看到东西。
rem
rem 关掉这个窗口不会结束对局。要结算就用 /quit，或点窗口里的「结束相关进程」。
rem ------------------------------------------------------------------
if not defined TM_PORT set "TM_PORT=8734"

echo.
echo   ==========================================
echo      Tokens 交易市场 - 观众席
echo   ==========================================
echo   端口         %TM_PORT%
echo   只读窗口     不能下单、不能快进
echo.

"%PY%" %PYARGS% run.py spectator 127.0.0.1 %TM_PORT%

echo.
echo   [已退出] 观众席已关闭，对局不受影响。
pause
