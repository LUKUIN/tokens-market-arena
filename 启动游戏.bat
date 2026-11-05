@echo off
chcp 936 >nul
cd /d "%~dp0"
title Tokens 交易市场 · AI 版 · 观众席
where python >nul 2>nul
if errorlevel 1 (
    echo.
    echo   [错误] 没有找到 python 命令。
    echo   请先安装 Python 3.10 或更高版本，安装时勾选 "Add python.exe to PATH"。
    echo.
    pause
    exit /b 1
)

rem ------------------------------------------------------------------
rem 本版不等待任何键盘输入。所有参数走环境变量，未设置的用下面默认值。
rem ------------------------------------------------------------------
if not defined TM_TRADER set "TM_TRADER=访客"
if not defined TM_EVENTS set "TM_EVENTS=1"
if not defined TM_FR     set "TM_FR=0"
if not defined TM_SLOT   set "TM_SLOT=0"

echo.
echo   ==========================================
echo      Tokens 交易市场 · AI 版
echo   ==========================================
echo   接口地址     http://127.0.0.1:8734
echo   参赛模型     %TM_TRADER%
echo   随机事件     %TM_EVENTS%
echo   金融回逆 %TM_FR%    老虎机 %TM_SLOT%
echo   GUI 只是只读观众席，没有投资界面。
echo.
python run.py
echo.
echo   [已退出] 服务与观众席都已关闭。
pause
