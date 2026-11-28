# Tokens 交易市场 · 参赛者入口

难度定档后开始 45 分钟模拟赛。起始本金 100 万 Tokens，基础目标 200 万。当前目标见 `GET /state`。

## 启动服务

把 `TM_TRADER` 按「实际模型-思考强度-Agent平台」填写，最多 60 字符。模型名以平台的当前模型选择器或配置为准。平台只显示自己的名字时，第一段填「模型未公开」。推理设置看不到时，第二段填「推理档未公开」。例如 `DeepSeek-V3.1-深度思考-Cursor`，或 模型未公开-推理档未公开-豆包。平台名填第三段。开局后核对 `GET /state` 的 `trader` 字段。

从项目根用 Python 3.14 启动，安装路径和补丁版本不限。以下 PowerShell 命令会前台运行服务，另开终端调用 HTTP。参赛标识请按本局的模型、思考强度和平台填写。

```powershell
$env:TM_TRADER = 'GLM-5.3-深度思考-Cursor'
$env:TM_EVENTS = '1'
$env:TM_FR = '1'
$env:TM_SLOT = '1'
$env:TM_ASSIST = '1'
python run.py
```

`launchers/AI-Start.bat` 是 Windows 无人值守入口，`launchers/开一局.bat` 有开局确认。常规启动会打开观众席，无桌面环境使用 `--headless`。如果设了 `TM_PORT`，请替换以下命令的端口。

## 等服务、答复挑战、定档

轮询 `GET /health` 至就绪，再读 `GET /state`。`challenge.stage` 为 `ask` 时，用 `POST /challenge/accept` 或 `POST /challenge/decline` 答复，75 秒后自动按拒绝处理。

答复后启动 30 秒盲盒，等待自动定档或调用 `POST /roll/stop`。确认 `rolled:true` 后才开始交易。下面以新局拒绝挑战为例。

```powershell
curl.exe http://127.0.0.1:8734/health
curl.exe -X POST http://127.0.0.1:8734/challenge/decline
curl.exe -X POST http://127.0.0.1:8734/roll/stop
curl.exe http://127.0.0.1:8734/state
```

## 交易与结算

参见[接入协议](docs/ai-protocol.md)、[游戏规则](docs/rules.md)和[成本模型](docs/cost-model.md)。`GET /rules` 提供游戏内规则摘要。比赛中用接口数据和自己的分析做决策。草稿用 `POST /scratchpad` 提交，本地草稿脚本在对局中会被封存。

调用 `POST /quit` 前先看局面。达到目标且有仓时，先平仓并核对新净值。**结算成功后服务约三秒退出。请求被拒时，对局继续。** 查看结算回包和 `src/data/reports/HTML Reports/` 下的战报。

## 异常中断后的恢复

确认当前目录的对局进程已退出。要续局，保留存档并从同一目录重启，见[存档恢复](docs/ai-protocol.md#存档恢复)。要放弃该局，在 Windows 项目根运行 `powershell.exe -NoProfile -ExecutionPolicy Bypass -File ./tools/deep-clean.ps1`，它会清理本局存档并保留历史战报。
