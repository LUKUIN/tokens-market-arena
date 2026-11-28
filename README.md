# Tokens 交易市场 · AI 版（源码版）

> 项目原始代码由 **DeepSeek Harness** 中的 **DeepSeek V4.1 Flash 1017（High）** 编写。

![观众席界面（1920×1080 档）](docs/spectator-1920x1080.png)

## 本仓库有三条产品线

同一个游戏内核，三种用法。三条分支的提交历史互不相干，各自独立演进：

| 分支 | 产品 | 谁在操作 | 说明 |
|---|---|---|---|
| [`main`](https://github.com/LUKUIN/tokens-market-arena/tree/main) | **AI 版（中文）** | 大模型走 HTTP 接口 | 中文观众席与文档 |
| [`english`](https://github.com/LUKUIN/tokens-market-arena/tree/english) | **AI 版（英文）** | 同上 | 全英文界面与文档 |
| [`human`](https://github.com/LUKUIN/tokens-market-arena/tree/human) | **人类版（中文）** | 玩家亲手点按钮 | 完整交互 GUI：投资界面、难度盲盒、规则窗 |

人类版与 AI 版共享交易和行情规则。人类版有操作界面，挑战池不包含场外求助类目标。
不想读源码的直接下人类版成品包：[人类版最新版本](https://github.com/LUKUIN/tokens-market-arena/releases/tag/human-v1.2.30)。

> **让 Agent 参赛？读 [`AGENTS.md`](AGENTS.md) 一页就够** —— 启动命令、定档、接口入口都在里面，详细接口见接入协议。
>
> 想换个 AI 参赛：打开 [`docs/给AI的启动提示词.txt`](docs/给AI的启动提示词.txt)，把两条虚线之间的整段复制给它，改一下第一行的路径就行。

[![CI](https://github.com/LUKUIN/tokens-market-arena/actions/workflows/ci.yml/badge.svg?branch=main)](https://github.com/LUKUIN/tokens-market-arena/actions/workflows/ci.yml)

> **中文** · [English](README.en.md)
>
> **EN**: Open-source 45-minute trading simulator with an HTTP API for LLMs and a desktop GUI for human players. Simulates spreads, slippage, price gaps, and financing costs, with HTML reports and JSON summaries after each match.

> 发行包见 [GitHub Releases](https://github.com/LUKUIN/tokens-market-arena/releases)。参赛模型通过 HTTP 接口交易，观众席提供行情查看和求助回复。
> **与人类版（`TokensMarket-OpenSource-Human`）不通用、不可混用**：本版没有投资界面、
> 没有开仓按钮、没有快进按钮。人类版有完整交互界面，两套源码不要互相复制界面文件。

---

## 这是什么

一个 45 分钟的交易模拟器：100 万本金，目标翻倍。参赛的是大模型，不是人。

- 模型通过 HTTP 接口下单、平仓、借贷、推进时间；
- 人类在旁边的观众席窗口看它的账户、持仓、权益曲线和活动流；
- 模型在「草稿纸」里写的东西，点观众席右上角「AI 行为」就能看到（只读）；
- 每局自动生成 HTML 报告，并把模型在「草稿纸」里写的内容一并并入。
  报告板块：关键指标 / 挑战任务 / 成本归因 / 交易明细 / 借贷账目 / 草稿纸 / 场外援助 / 关键事件。

局内有两个重点机制，完整规则见「一局的流程」与 `GET /rules`：

- **一大波预警**：整局 0–3 次的突发大事件（四档等概率各 25%；常规阶段间隔至少 36 步，末段可缩短），屏幕正中弹出横幅 + Windows 系统提示音，隔两个行情步后一次性涌出 3–5 条冲击事件；观众席「运行状态」常驻显示本局总次数 / 已触发 / 未触发
- **挑战任务**：开局有 75 秒决定是否开启。定档时从 20 条候选中抽一条结果任务和两条不同类型的过程任务。「孤注一掷」为稀有签，抽中后目标翻倍，老虎机和借款造成的目标上浮按 50%–100% 计算。净值任务按终场清算判定。

---

## 运行环境与必需组件

| 运行方式 | 所需组件 |
|---|---|
| Windows WPF 观众席 | Python 3.14 和 [.NET 8 Desktop Runtime](https://dotnet.microsoft.com/download/dotnet/8.0)（x64） |
| Windows tkinter 观众席 | Python 3.14，含 Tcl/Tk |
| 无桌面服务 | Python 3.14，仓库提供 Linux 容器配置 |

发行 ZIP 内含 WPF 界面。重编才需要 .NET 8 SDK。设 `TM_WATCH_IMPL=py` 可选用 tkinter，WPF 程序缺失时也会自动回退。若 WPF 文件存在但启动失败，需手动选择回退。Python 服务使用标准库。AI 入口遇到其他 Python 版本会返回码 2，3.14 的补丁号和安装路径不限。

## 快速开始

启动顺序和 PowerShell 命令见 [AGENTS.md](AGENTS.md)，换模型参赛可复制[启动提示词](<docs/给AI的启动提示词.txt>)。

- 在项目根运行 `python run.py`，或用 Windows 无人值守入口 `launchers/AI-Start.bat`。终端启动不提问，挑战答复属于局内 HTTP 流程。
- Windows 双击 `launchers/开一局.bat` 时，五秒内未确认会取消开局。
- 补挂观众席前先确认原服务仍在运行，再用 `python run.py spectator 127.0.0.1 8734`，端口换成本局所用值。端口无对局时会提示并退出。
- 无桌面环境用 `python run.py --headless`，默认回环地址、端口 8734。并行开局需使用不同目录与端口，避免共用存档和守卫文件。

| 设置 | 脚本入口默认值及用途 |
|---|---|
| `TM_TRADER` | 启动前填写模型、思考强度、平台。引擎将本局标记为未命名时，达标不计入成绩。 |
| `TM_EVENTS` | `1`。设 `0` 关闭普通新闻与「一大波」，仍有基础跳空及市场深度冲击。 |
| `TM_FR`、`TM_SLOT`、`TM_ASSIST` | `1`。启动前设 `0` 可关闭相应功能，交互演示入口会另行询问。 |
| `TM_PORT`、`TM_IDLE_ABORT` | `8734` 与 `0`。Windows 五秒确认入口的无活动保护默认 12 分钟。 |
| `TM_WATCH_IMPL` | 设 `py` 使用 tkinter，否则优先 WPF。 |

## 观众席界面

> 本节描述的是默认的 **C# / WPF 观众席**（`viewer-cs/TokensWatch/`，`run.py` 起的第一个窗口）。
> tkinter 版（`src/tm_watch_ai.py`）自 v1.2.22 起只是回退路径：C# 没构建、或显式设了
> `TM_WATCH_IMPL=py` 时才会出现，分区与下方表格一致但实现细节不同。

交易走 HTTP。观众席可查看账户、行情、活动流和 AI 草稿，也可回复或驳回求助。

观众席收到求助时可能弹出提示。关闭提示框后，求助仍保留在「外部的怜悯」窗口，直到有人回复或驳回。观众席也可以请求停服。

分区从上到下：

| 区域 | 内容 |
|---|---|
| 顶栏（浅色卡片） | 市场名「TOKENS 交易市场」、参赛模型标识、模式徽章、全局事件状态（优惠融资 / 老虎机）、结束进程 / 最小化 / AI 行为 / 外部的怜悯 |
| 指标卡 | 账户权益、累计盈亏、保证金水平、目标进度 |
| 状态条 | 可贷额度 / 现金 / 已借 / 欠款 / 利息；目标 / 回撤 / 夏普 / 笔数 / 盈利因子 / 费息；账本自检告警位；上局异常退出提示 |
| 权益曲线 | 主视觉，Y 轴自适应（按本局极值留白，始终把本金线与目标线纳入量程） |
| 运行状态 | 账本自检、黑天鹅频率、流动性、快进额度、全局事件、峰值、谷值、回撤\|夏普、一大波（本局总次数 / 已触发 / 未触发） |
| 持仓明细 | 主窗按档位预览 7、4 或 2 行；**从第 2 条持仓起**标题行右上角就有「更多」，点开是随对局同步刷新的完整表（不分页）；空仓显示空状态 |
| 报价台 | 7 个品种的当前价、涨跌幅、以及由 `price_history` 画的迷你走势线 |
| 活动流 | 右栏只画最近 30 条；点「更多」打开全量列表（按分类筛选：全部 / 黑天鹅 / 流动性枯竭 / 随机事件 / 开仓平仓 / 风险），可查看这个窗口已收到的事件；中途补挂时只收到服务保留的近期事件 |

WPF 窗口按显示器的物理分辨率选档：2560×1440 及以上用 **1920×1080**，1920×1080 及以上用 **1600×900**，更小的屏用 **1280×720**。这些尺寸是窗口的物理像素，Windows 缩放不会改变档位或外框尺寸。工作区放不下时等比缩小，标题栏显示实际尺寸。可设置 `TM_WATCH_SIZE=1600x900` 手动指定像素尺寸。

> 账户和行情数据来自模拟引擎，经 `/state` 刷新。成交和成本明细见 HTML 战报。

### 观众席掉线时

常规启动时，观众席在独立子进程中通过 HTTP 刷新。在服务仍运行时，单独关闭窗口或观众席轮询失败不会中断对局。若窗口反复显示连接错误，先确认正确端口上的服务在运行。tkinter 版会把诊断写入 `src/data/watch.log`。

确认服务仍在运行后，用 `launchers/只开观众席.bat` 补挂 tkinter，或用下节的 WPF 入口补挂 WPF。

## C# 观众席（默认界面，tkinter 为回退）

`viewer-cs/` 里是一个独立的 WPF 观众席，用来替代 `src/tm_watch_ai.py` 那个 tkinter 窗口。它通过本地 HTTP 刷新行情、账户与活动流，也可回复求助和请求停服。交易由 Agent 通过 HTTP 接口发起。

### 为什么会有这个

tkinter 的 Canvas 没有抗锯齿，曲线在斜向上永远带毛边；Fluent 的半透明、阴影、Mica 也做不出来。C# + WPF 是矢量渲染，这些是白送的。

### 需要什么

- Windows x64
- .NET 8 SDK（构建）或 .NET 8 Desktop Runtime（只运行）

### 怎么构建

```bat
launchers\构建观众席(新版).bat
```

产物在 `viewer-cs/TokensWatch/bin/Release/net8.0-windows/TokensWatch.exe`。

### 怎么启动

常规启动会自动打开 WPF 观众席。已有对局且需补挂 WPF 窗口时，从项目根运行：

```bat
launchers\只开观众席(新版).bat
```

自定义端口时，补挂 WPF 前将 `TM_WATCH_API` 设为该对局的 HTTP 地址。两个观众席可以同时开：WPF 的单实例锁是 `Global\TokensWatchViewerCs`，不占 tkinter 版用的 8735 端口。

### 与 tkinter 版的关系

- 并存，不互斥；哪边看着顺眼用哪边
- 两种观众席均可查看行情、答复求助并提交停服请求
- 依赖零安装（不放 NuGet 包，图表是 WPF 矢量自绘），`requirements.txt` 不受影响

## 一局的流程

1. 启动服务，等待 `GET /health` 就绪。
2. 在 75 秒内答复是否开启挑战，超时按拒绝处理。之后自动开始 30 秒盲盒。
3. 等抽选结束或调用 `POST /roll/stop`。定档即开始 45 分钟计时，同时公布已启用的挑战目标。
4. 确认 `rolled:true` 后交易。行情会自然推进，快进另有额度和冷却。
5. 调用 `/quit` 前查询局面。达标且还有持仓时先平仓，重新核对净值。**结算成功后服务约三秒退出。请求被拒时，对局继续。** 时间到或触发账户结算条件也会自动清算，详见[游戏规则](docs/rules.md)。

## HTTP 接口

全部路由、字段和回包见[接入协议](docs/ai-protocol.md)。`GET /prices` 返回当前报价。`GET /state?history=0` 清空返回的价格历史，仍有权益曲线和近期事件。`GET /rules` 提供游戏内规则摘要。

## 给 Agent 的提示词模板（可直接复制）

复制[启动提示词](<docs/给AI的启动提示词.txt>)并替换本机项目路径。

## 草稿纸终端（可选）

对局中用 `POST /scratchpad` 写笔记，请求体为 UTF-8 JSON，例如 `{"text":"等待点差恢复再下单"}`。`GET /scratchpad` 可读，`?count=1` 可数条数，POST 传 `{"clear":true}` 可清空。本地草稿脚本属于守卫封存的文件。只有实际提交的草稿进入战报。

## 源码守卫（防作弊）

常规启动会封存 `src/tm_engine.py`、`src/tm_api.py` 和 `src/scratchpad.py`。执行诱饵会触发终止。正常退出后源码自动恢复，异常中断请等当前目录的对局进程退出，再按 [AGENTS.md](AGENTS.md) 处理。

## 进程深度清理

此操作会移除本局主档及备份。需要续局时请先保留存档并重启。确定放弃该局后，先确认本目录的对局已停止，再从项目根运行下列命令。

```bash
powershell.exe -NoProfile -ExecutionPolicy Bypass -File ./tools/deep-clean.ps1
```

> **由 AI 或脚本调用时请用上面这条命令**，不要直接跑 `launchers\进程深度清理.bat`：
> 它内部有两个 `pause`（管道或重定向喂 stdin 会卡住），而且用 GBK 输出（UTF-8 终端下是乱码）。
> `tools\deep-clean.ps1` 是同一套逻辑的非交互版本；**退出码 0 即成功**。
> 人工双击 `launchers\进程深度清理.bat` 仍然可用（加 `-y` 参数则跳过暂停）。

脚本会检查当前目录的运行标记，按需恢复源码，只清除已知的运行时文件，并保留战报和其他进程。

---

## 目录结构

```
项目根目录/
├── run.py                  统一入口（常规开局 / --interactive / server / --headless / spectator / state / report-retry）
├── bench.py                配对多轮评测：同组 seed 跑多局并输出统计
├── guard.py                源码封存守卫（run.py 自己调用，不要手动起）
├── requirements.txt        无第三方依赖（占位文件）
├── Dockerfile              容器镜像（python:3.14-slim · --headless）
├── README.md / README.en.md
├── AGENTS.md               给 Agent 的单页入口 + 项目地图（AI 先读这个）
├── launchers/              所有双击入口（内部自动切回仓库根）
│   ├── 开一局.bat                双击入口（5 秒内按 Y 才启动，不按就取消开局）
│   ├── AI-Start.bat              无人值守入口（不做确认；脚本 / Agent 专用）
│   ├── 只开观众席.bat            tkinter 观众席：窗口被误关时补挂
│   ├── 构建观众席(新版).bat      C# 观众席的构建入口（需要 .NET 8 SDK）
│   ├── 只开观众席(新版).bat      C# 观众席的启动入口
│   └── 进程深度清理.bat          人工双击用（含 pause）
├── tools/
│   └── deep-clean.ps1      清理本体；AI 请直接调用它（非交互，退出码 0 即成功）
├── src/
│   ├── tm_engine.py        引擎（纯逻辑）
│   ├── tm_api.py           HTTP 接口
│   ├── tm_watch_ai.py      只读观众席
│   ├── scratchpad.py       草稿纸终端
│   ├── app.ico / warn.ico  图标
│   └── data/               运行时生成：存档、备份、草稿和战报
├── viewer-cs/TokensWatch/  C# / WPF 观众席（默认界面；tkinter 为回退）
│   ├── Controls/           权益曲线与迷你走势线（纯 WPF 矢量自绘，无第三方库）
│   ├── Services/           HTTP 客户端（显式绕过系统代理）
│   ├── Panels/             四个附属窗口：AI 行为 / 外部的怜悯 / 活动流 / 持仓
│   └── Theme/              Fluent 样式：卡片、按钮、表格、滚动条
├── tests/                  unittest 用例（python -m unittest discover -s tests）
├── docs/
│   ├── rules.md            完整规则      · rules.en.md 英文版
│   ├── cost-model.md       成本模型      · cost-model.en.md 英文版
│   ├── ai-protocol.md      接入协议      · ai-protocol.en.md 英文版
│   └── 给AI的启动提示词.txt  可直接粘贴给 Agent 的启动文本
└── examples/reports/       6 份代表性报告 · README.en.md 英文版
```

---

## 与人类版的区别（不要混用）

| 项 | AI 版（本仓库） | 人类版 |
|---|---|---|
| 界面 | 观众席（C# / WPF，交易走 HTTP） | 完整交互 GUI（可开平仓、借贷、快进） |
| 投资界面 | 无 | 有 |
| 开仓方式 | HTTP `/open` | 点按钮 |
| 快进 | `/fastforward` | 两个档位按钮（5 分钟 / 3 分钟） |
| 草稿纸 | 有 | 无 |
| 分辨率 | 按显示器自动选档（1920×1080 / 1600×900 / 1280×720） | 同左，两版共用 `DisplayProfile.cs` |
| 进程清理脚本 | 有 | 无 |

---

## 实测数据

以下是六份历史单局记录（45 分钟 / 100 万本金 / 基础目标 200 万）。版本、设置和行情路径可能不同。

| 模型 | 最终权益 | 盈亏 | 结果 |
|---|---:|---:|---|
| qwen3.8-flash | **2,063,829** | **+106.38%** | ✅ 唯一达成 |
| GLM-5.3-Flash | 909,030 | −9.10% | ✗ |
| Doubao-Seed | 676,243 | −32.38% | ✗ |
| WorkBuddy-Agent | 230,483 | −76.95% | ✗ |
| DeepSeek-Flash | 163,587 | −83.64% | ✗ |
| （某模型单局） | −1,298,657 | −229.87% | ✗ 穿仓 |

---

## 结算与清算

开仓保证金与手续费必须能由可用保证金覆盖。计入本笔手续费、点差和滑点后的净值还须覆盖预计维持保证金的 150%。基础维持保证金率 10%、净值 100 万时，起始总名义敞口上界为 667 万，实际可开仓规模受成交成本、事件和可用保证金影响。

保证金水平低于 100% 进入追缴，恢复到 100% 可解除；30 个行情步未恢复则强平，低于 50% 立即强平。净值为负会结束对局，只有现金为负时才有默认 60 秒自救窗口。借款同时增加现金与欠款。

已达标且仍持仓时，先平仓并核对净值，再请求 `/quit`。未达标时正常退出会按弃权记录。自动结算按正常成交成本清仓并清偿贷款，回包里的 `settled` 与 `warnings` 可核查结算。详见[成本模型](docs/cost-model.md)。战报导出失败时，按[接入协议](docs/ai-protocol.md#结算与战报)补导。

## 账本自检与配对评测

### 账本自检（`audit`）

每局清算后、以及每次 `/state`，都会跑一次不变量自检，共三条恒等式：

| 检查项 | 恒等式 |
|---|---|
| 手续费 | 累计手续费 == 成交流水 `fee` 之和 |
| 贷款 | `loan.balance` == `borrowed − repaid + interest` |
| 持仓 | 方向只能是 `LONG` / `SHORT`，手数必须为正 |

> 早期版本还有第 4 条「权益 == 现金 + 浮盈 − 欠款」，但它与 `equity()` 是同一个公式、恒真，不构成独立校验；v1.2.10 起移除。

`/state` 里的 `audit` 是字符串数组：**空数组表示三条全部成立**；非空时每条是一句可读的告警。
结算时审计结论直接并入 `warnings`，`settled` 随之变 `false`——账目对不上不会被当成正常结算。

同一份结论有三个出口，不必去翻 JSON：

- `/state` 的 `audit` 字段（给 Agent 与脚本）
- 观众席状态条（异常时亮红字，正常时不占位）
- 报告「关键指标」下方一行（绿色=通过，红色=未通过并列出具体哪条）

### 事件序号

每条事件带 `seq`（单调递增）与 `session`（会话 ID），报告与审计日志可以按序号定位到同一条事件。

### 机器可读摘要

HTML 在 `src/data/reports/HTML Reports/`，同名摘要在 `src/data/reports/JSON Reports/`。JSON 包含以下字段。
版本、seed、盈亏、回撤、夏普、成本分项、结算结果、账本自检结论。`bench.py` 与 CI 只读这份 JSON，不解析 HTML。

> **v1.2.20 口径修正**：`pnl` 与 `pnl_pct` 一律以本金（新增字段 `genesis`）为基准，
> 与 HTML 报告、`/state` 完全一致。此前用的是权益曲线首点，玩家在第一个 tick 之前开仓时，
> 首点已经扣过点差/滑点/手续费，JSON 会比另外两处少算一笔开局成本。`start_equity` 字段保留原义
> （曲线首点），需要本金请读 `genesis`。

### 复现一局

报告抬头印两样东西：`随机种子` 与 `难度档位 索引`。它们的能力边界不同，别混用：

| 想要什么 | 需要的参数 | 说明 |
|---|---|---|
| 同样的行情（价格 / 跳空 / 新闻） | `TM_SEED=<种子>` | 未定档时按 1.5% 基准概率；定档后按档位概率，档位不同则行情必然不同 |
| 同样的难度档位 | `TM_ROLL_INDEX=<索引>` | 0-24，`索引 = gap + liq × 5`；设了它，盲盒无论何时叫停都定格在这一档 |
| 复现行情路径 | 两个都给 | 使用同版本引擎与相同的随机事件设置 |

只给 seed 不给索引，重开时抽到哪档取决于叫停时刻的墙钟（每 2.5 秒一圈），大概率不是同一档。
`bench.py run` 加 `--roll-index N` 可以让多局对齐同一档位。

`GET /state` 的 `seed` 字段在对局中恒为 `null`，结算后才返回——参赛者拿不到种子，也就无法按种子预演行情。

### 配对评测（`bench.py`）

离线跑分关闭挑战任务并按模拟时钟推进。普通基准为 540 步，策略仍可能触发合法的提前结算。配对比较请对齐种子、设置与引擎版本。`--roll-index` 可锁档，未指定时读有效的 `TM_ROLL_INDEX`，否则由种子确定。

```bash
python bench.py run --seeds 1-5 --policy noop --out benchmark-output
python bench.py run --seeds 1-5 --policy probe --out benchmark-output
```

`noop` 是不交易基准，`probe` 周期性交易测试成本，`oracle` 使用未来价格作离线诊断。每局单独生成 JSON 摘要。通过 HTTP 横评时可统一设置 `TM_TAIL_SPEED=1`，因为默认首次达标后行情间隔约 1.25 秒，总步数取决于何时达标。

## 已知限制

- 桌面观众席面向 Windows（观众席的窗口图标、提示音走 Win32 API）。
- 观众席是独立子进程：关闭观众席或观众席自身启动失败不会中断已启动的对局。窗口需要桌面环境，无桌面环境请用 `--headless`。服务端口被占用会阻止开局。
- 源码版不含成品包的 `.pyd` 与 manifest 校验；`TM_SIGN_KEY` 默认是 dev 占位值，正式比赛请自行设置。
