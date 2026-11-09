@echo off
chcp 936 >nul
cd /d "%~dp0.."
rem ==================================================================
rem 无人值守入口（供脚本 / Agent 调用）。
rem v1.2.13：不再复制一份查找与启动逻辑，直接委托给 开一局.bat ——
rem   · TM_NO_CONFIRM=1  跳过 5 秒误点确认
rem   · TM_IDLE_ABORT=0  不启用无活动自动收尾
rem     （Agent 可能长时间观察/推理，那不是「没人操作」）
rem 这样「启动方式」全项目只有一份真相。
rem ==================================================================
setlocal
set "TM_NO_CONFIRM=1"
if not defined TM_IDLE_ABORT set "TM_IDLE_ABORT=0"

call "%~dp0开一局.bat" %*
goto :eof
