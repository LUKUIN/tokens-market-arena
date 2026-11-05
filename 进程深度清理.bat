@echo off
chcp 936 >nul
title 进程深度清理 - Tokens 交易市场
echo.
echo   ============================================================
echo     进程深度清理 - Tokens 交易市场
echo   ============================================================
echo.
echo   作用：杀掉所有残留的游戏进程（按命令行 + 端口识别），
echo         并清掉 data 目录下的运行时文件和 _agent 目录。
echo         reports 子目录里的历史战报不会被动。
echo.
echo   什么时候用：每次运行「一键重置游戏」之后，立刻跑这个。
echo.
pause
powershell -NoProfile -ExecutionPolicy Bypass -File "%~dp0deep-clean.ps1"
echo.
pause
