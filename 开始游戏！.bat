@echo off
chcp 936 >nul
cd /d "%~dp0"
title Tokens 交易市场 · 人类版
where python >nul 2>nul
if errorlevel 1 (
    echo.
    echo   [错误] 没有找到 python 命令。
    echo   请先安装 Python 3.10 或更高版本，安装时勾选 "Add python.exe to PATH"。
    echo.
    pause
    exit /b 1
)
echo.
echo   ==========================================
echo      Tokens 交易市场 · 人类版   启动中
echo   ==========================================
echo   进入后依次是：免责声明 - 名字 - 随机事件 - 难度盲盒 - 规则窗 - 主界面
echo.
python run.py
echo.
echo   [已退出] 服务与界面都已关闭。
pause
