@echo off
chcp 936 >nul
cd /d "%~dp0"
title Tokens 交易市场 · AI 版 · 观众席
setlocal

rem ==================================================================
rem 固定运行时：只能用下面这个 Python 3.14.7。
rem GUI 控件与 .pyc 都按 3.14 编译，换成 where python / py -3.x
rem 找到的别的版本会直接起不来。换机时只改这一行。
rem ==================================================================
set "PY=C:\Users\User\AppData\Local\Programs\Python\Python314\python.exe"
if not exist "%PY%" (
    echo.
    echo   [错误] 找不到固定运行时：
    echo     %PY%
    echo   本版只支持 Python 3.14.7，不要改用其它 Python。
    echo.
    pause
    exit /b 1
)

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
"%PY%" run.py
echo.
echo   [已退出] 服务与观众席都已关闭。
pause
