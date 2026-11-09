@echo off
chcp 936 >nul
cd /d "%~dp0"
title Tokens 交易市场 · AI 版 · 观众席
setlocal

rem ==================================================================
rem 运行时只接受 Python 3.14：GUI 控件与 .pyc 都按 3.14 编译。
rem 下面按顺序查找，任一命中即可：
rem   1) 本机固定安装路径   2) py 启动器的 -3.14   3) PATH 里的 python（先校验版本）
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
rem 本版不等待任何键盘输入。所有参数走环境变量，未设置的用下面默认值。
rem ------------------------------------------------------------------
if not defined TM_TRADER set "TM_TRADER=访客"
if not defined TM_EVENTS set "TM_EVENTS=1"
if not defined TM_FR     set "TM_FR=1"
if not defined TM_SLOT   set "TM_SLOT=1"
if not defined TM_ASSIST set "TM_ASSIST=1"
if not defined TM_PORT   set "TM_PORT=8734"

echo.
echo   ==========================================
echo      Tokens 交易市场 · AI 版
echo   ==========================================
echo   接口地址     http://127.0.0.1:%TM_PORT%
echo   参赛模型     %TM_TRADER%
echo   随机事件     %TM_EVENTS%
echo   优惠融资 %TM_FR%    老虎机 %TM_SLOT%    外部的怜悯 %TM_ASSIST%
echo   观众席会随服务一起打开，GUI 只读。
echo   以上三项只能在开局前设定，进入对局后不再提供开关。
echo.
rem run.py 自己会封存源码、退出时还原。这里不要再起一份守卫：
rem 起两份守卫会封两次，第二次封的是已经换上去的诱饵，真源码就再也还原不回来了。
"%PY%" %PYARGS% run.py
echo.
echo   [已退出] 服务与观众席都已关闭。
pause
