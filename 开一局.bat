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
if not defined TM_IDLE_ABORT set "TM_IDLE_ABORT=12"
set "IDLE_WARN=%TM_IDLE_ABORT%"
if "%IDLE_WARN%"=="0" set "IDLE_WARN=（已关闭）"

echo.
echo   ==========================================
echo      Tokens 交易市场 · AI 版
echo   ==========================================
echo   接口地址     http://127.0.0.1:%TM_PORT%
echo   参赛模型     %TM_TRADER%
echo   随机事件     %TM_EVENTS%
echo   优惠融资 %TM_FR%    老虎机 %TM_SLOT%    外部的怜悯 %TM_ASSIST%
echo   5 秒内按 Y 才启动对局；不按则清理退出。
echo   要让 AI 参赛，请在本目录运行：python run.py
echo.
echo   !! 本版是 AI 参赛版：界面只读，没有下单 / 平仓 / 快进按钮。
echo   !! 人类要玩请用 TokensMarket-OpenSource-Human。
echo   !! 用 python run.py 启动时，定档后 %IDLE_WARN% 分钟无操作会自动结算（TM_IDLE_ABORT）。

rem ==================================================================
rem v1.2.12：本入口增加「误点保护」，但保留真正的启动能力。
rem   - 人类双击（有控制台）：5 秒内不按 Y 就清理退出，不会空转 45 分钟。
rem   - 脚本 / AI 调用（无控制台 stdin）：choice 返回 255，直接启动对局。
rem 这样既拦住误点，也不会误伤真正要比赛的 Agent。
rem ==================================================================
echo.
echo   5 秒内按 Y 启动对局（仅限已有 Agent 会连上来操作）；
echo   不按则自动清理并退出。
choice /c YN /t 5 /d N /n /m " " 2>nul
if errorlevel 255 goto :direct_start
if errorlevel 2 goto :abort_start

:direct_start

rem run.py 自己封存源码、退出时还原；这里不要再额外起一份 guard.py。
"%PY%" %PYARGS% run.py
echo.
echo   [已退出] 服务与观众席已关闭。
pause
goto :eof

:abort_start
echo.
echo   已取消。正在清理残留进程与临时文件……
powershell -NoProfile -ExecutionPolicy Bypass -File "%~dp0deep-clean.ps1"
echo.
echo   [已清理]
echo   - 要让 AI 参赛：在本目录运行  python run.py
echo   - 人类要玩：请用 TokensMarket-OpenSource-Human
echo.
pause
goto :eof
