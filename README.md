# Tokens 交易市场 · AI 版（源码版）

[![CI](https://github.com/LUKUIN/tokens-market-arena/actions/workflows/ci.yml/badge.svg?branch=main)](https://github.com/LUKUIN/tokens-market-arena/actions/workflows/ci.yml)

> **中文** · [English](README.en.md)
>
> **EN**: A 45-minute trading simulator where LLMs trade with real friction — spread,
> slippage, gap risk and overnight interest. One model made +106%, another blew up at
> −229%. Zero dependencies, Windows + Python 3.10+.

> 对应成品包 **v97**。参赛模型通过 HTTP 接口操作，GUI 只是一个**只读观众席**。
> **与人类版（`TokensMarket-OpenSource-Human`）不通用、不可混用**：本版没有投资界面、
> 没有开仓按钮、没有快进按钮。人类版有完整交互界面，两套源码不要互相复制界面文件。

---

## 这是什么

一个 45 分钟的交易模拟器：100 万本金，目标翻倍。参赛的是大模型，不是人。

- 模型通过 HTTP 接口下单、平仓、借贷、推进时间；
- 人类在旁边的观众席窗口看它的账户、持仓、权益曲线和活动流；
- 模型在「草稿纸」里写的东西，点观众席右上角「AI 行为」就能看到（只读）；
- 每局自动生成 HTML 报告，并把模型在「草稿纸」里写的内容一并并入。

---

## 快速开始

**本版全程不询问输入。** 所有配置走环境变量，没设就用默认值——没有 `input()`、没有「按任意键」、没有二次确认。

### 给 Agent / 脚本（常态）

`python run.py` 是**前台阻塞**命令，会一直跑到本局结束（最长 45 分钟）。执行器若把它当普通命令等待返回，必然触发自己的超时并 kill 进程，服务随之消失，之后所有请求都是 `connection refused`。

**必须用 `python run.py`，它会同时打开观众席窗口。** 不要用 `run.py server`——那是无头模式，没有窗口，人类看不到这一局在发生什么。

必须后台启动、再轮询就绪：

```bash
cd <项目目录>

TM_TRADER="模型名-思考强度-Agent平台" TM_EVENTS=1 TM_FR=0 TM_SLOT=0 \
  nohup python run.py > run.log 2>&1 &

for i in $(seq 1 30); do
  curl -sf http://127.0.0.1:8734/health >/dev/null 2>&1 && break
  sleep 1
done
```

Windows `cmd`：

```bat
cd /d <项目目录>
start "" /b python run.py
```

不要用固定的 `sleep 6 && curl`——启动需要 3~8 秒，机器慢时会假失败。

**启动后立刻定档**，否则 `/tick` 不推进：

```bash
curl -X POST http://127.0.0.1:8734/roll/stop
```

### 人手动玩（双击）

`启动游戏.bat`——同样不问任何问题，只把即将使用的参数打印出来。

### 只要服务不要窗口

```bash
python run.py server 127.0.0.1 8734
```

无桌面环境必须用这个。默认模式会创建 Tk 窗口，没有桌面时创建失败会带崩整个进程。

环境变量：

| 变量 | 作用 |
|---|---|
| `TM_TRADER` | 参赛模型标识，格式 **【模型名-思考强度-Agent平台】**，最长 60 字符，缺省「访客」 |
| `TM_EVENTS` | `1` 开启随机事件 / `0` 理想情况（只有黑天鹅跳空） |
| `TM_FR` | `1` 开启【金融回逆】：整局借款 **2 次**，目标区间 `-20%~100%` |
| `TM_SLOT` | `1` 开启【老虎机】：整局 **3 次**，`1~200000` 且不超当前权益，80% 空 / 15% 5 倍 / 5% 10 倍 |
| `TM_PORT` | 端口号 | 服务端口，默认 `8734`。被占用时改这个，别改代码 |
| `TM_SIGN_KEY` | 存档 HMAC 密钥，不设则用 dev 占位值 |

要求：Python 3.10+、Windows（观众席依赖 Win32 图标），无第三方依赖。

---

## 一局的流程

0. **开局问答（顺序固定）**：玩家名 → 是否开启随机事件 → 是否开启【金融回逆】→ 是否开启【老虎机】。
   全部用环境变量给足（`TM_TRADER`/`TM_EVENTS`/`TM_FR`/`TM_SLOT`）就完全不问；
   缺哪个 `run.py` 就问哪个，`input()` 读到 EOF 时取「关」。
   **两个全局开关在「随机事件」之后、「抽难度」之前决定**；
1. 服务启动，观众席窗口出现，标题栏先显示「难度抽选中」；
2. 30 秒难度盲盒：模型可以 `POST /roll/stop` 提前叫停，不叫停则到点自动定格；
3. 定档那一刻才开始计时——抽难度的 30 秒不计入 45 分钟；
4. 模型开始交易：`/state` 看局面 → `/open` `/close` 下单 → `/tick` 推进；
5. 45 分钟到、目标达成、爆仓、或 `/quit`，结算并生成报告；
6. `/quit` 后约 3 秒服务与观众席自动退出。

---

## HTTP 接口

服务地址默认 `http://127.0.0.1:8734`。

### GET

| 端点 | 返回 |
|---|---|
| `/health` | `{ok, tick, equity, finished}` |
| `/rules` | 完整规则文本 + 参数（含 38 种随机事件说明） |
| `/state` | 账户、持仓、贷款、行情、历史、难度、快进状态 |
| `/prices` | 报价表 |
| `/roll/state` | 盲盒倒计时与当前定格结果 |
| `/scratchpad` | 本局草稿纸全部条目 |
| `/special` | 两个全局开关状态 + 剩余次数（`fr`/`slot`/`fr_left`/`slot_left`/`slot_win`） |

### POST（JSON body）

| 端点 | 参数 | 说明 |
|---|---|---|
| `/open` | `{pair, side, lots, leverage}` | 开仓 |
| `/close` | `{pair, lots}` | 平仓 |
| `/close_all` | — | 全平 |
| `/tick` | — | 推进一个 tick（**消耗快进额度、受冷却约束**） |
| `/fastforward` | `{seconds}` | 快进一档（300 或 180），消耗额度 |
| `/loan` | `{amount}` | 借款；上浮比例在借款时抽定，这是代价 |
| `/repay` | `{amount}` | 还款，省略则全额 |
| `/trader` | `{name}` | 设置玩家名 |
| `/scratchpad` | `{text}` | 追加一条草稿 |
| `/special` | `{name, on}` | 切换全局开关（`fr` / `slot`）；局内开启扣 30 万现金 |
| `/slot` | `{amount}` | 老虎机下注：`1~200000`、≤当前权益、整局 3 次 |
| `/pause` / `/begin` | — | 冻结 / 解冻计时 |
| `/roll/start` / `/roll/stop` | — | 开始 / 叫停难度盲盒 |
| `/reset` | — | 重开一局（清 data 除 reports 外） |
| `/quit` | — | 正常结算并退出 |
| `/shutdown` | — | 立即停服（会留一份异常退出报告） |

> **注意**：`/tick` 与 `/fastforward` 共用同一套额度与冷却。额度 900 秒、档位 300/180 秒、
> 冷却 120/90 秒；冷却期内调用会被拒绝，只能等服务端每 5 秒一次的自动推进。

---

## 草稿纸终端（可选）

让模型在对局中记录判断与对策。它不占观众席主界面的版面——
观众随时点右上角的 **「AI 行为」** 按钮，就能打开只读窗口查看 AI 写了什么；
赛后内容同样并入 HTML 报告。

```bat
python src/scratchpad.py "AURA 偏离均值 8%，准备做空"
python src/scratchpad.py --list     查看本局已记内容
python src/scratchpad.py --count    只看条数
python src/scratchpad.py --clear    清空
python src/scratchpad.py            连续输入模式（Ctrl+C 退出）
```

也可以走 HTTP：`GET /scratchpad`、`POST /scratchpad {"text": "..."}`。

每写一条立刻落盘（`src/data/.scratchpad.jsonl`），中途关终端不丢；结算/重置时自动清除。
不用也可以——报告里会写「无内容」。

---

## 进程深度清理

对局结束、或启动异常（端口被占、窗口不出现）时运行：

```bash
cd <项目目录>
powershell -NoProfile -ExecutionPolicy Bypass -File deep-clean.ps1
```

> **由 AI 或脚本调用时请用上面这条命令**，不要直接跑 `进程深度清理.bat`：
> 它内部有两个 `pause`（管道或重定向喂 stdin 会卡住），而且用 GBK 输出（UTF-8 终端下是乱码）。
> `deep-clean.ps1` 是同一套逻辑的非交互版本，已强制 UTF-8 输出；**退出码 0 即成功**。
> 人工双击 `进程深度清理.bat` 仍然可用（加 `-y` 参数则跳过暂停）。

它做两件事：

1. 按命令行关键字 + 8734–8745 端口，杀掉所有残留的 python 游戏进程；
2. 清掉 `src/data/` 下除 `reports/` 之外的全部运行时文件（含草稿纸缓存）。

`reports/` 是历史战报，不会被删。

---

## 目录结构

```
TokensMarket-OpenSource-AI-v97/
├── run.py                  统一入口（ai / --interactive / server / state）
├── 启动游戏.bat            Windows 双击入口
├── 进程深度清理.bat        人工双击用（含 pause）
├── deep-clean.ps1          清理本体；AI 请直接调用它（非交互）
├── src/
│   ├── tm_engine.py        引擎（纯逻辑）
│   ├── tm_api.py           HTTP 接口
│   ├── tm_watch_ai.py      只读观众席
│   ├── scratchpad.py       草稿纸终端
│   ├── app.ico / warn.ico  图标
├── docs/
│   ├── rules.md            完整规则      · rules.en.md 英文版
│   ├── cost-model.md       成本模型      · cost-model.en.md 英文版
│   └── ai-protocol.md      接入协议      · ai-protocol.en.md 英文版
├── examples/reports/       4 份代表性报告 · README.en.md 英文版
└── src/data/               运行时生成：session.json、reports/、.scratchpad.jsonl
```

---

## 与人类版的区别（不要混用）

| 项 | AI 版（本仓库） | 人类版 |
|---|---|---|
| 界面 | 只读观众席 | 完整交互 GUI |
| 投资界面 | 无 | 有 |
| 开仓方式 | HTTP `/open` | 点按钮 |
| 快进 | `/fastforward` + `/tick` | 两个按钮 |
| 草稿纸 | 有 | 无 |
| 分辨率 | 固定 1920×1080 版式 | 四种可选，自动缩放 |
| 进程清理脚本 | 有 | 无 |

---

## 实测数据

6 个大模型在同一套规则下各跑一局（45 分钟 / 100 万本金 / 目标 200 万）：

| 模型 | 最终权益 | 盈亏 | 结果 |
|---|---:|---:|---|
| qwen3.8-flash | **2,063,829** | **+106.38%** | ✅ 唯一达成 |
| GLM-5.3-Flash | 909,030 | −9.10% | ✗ |
| Doubao-Seed | 676,243 | −32.38% | ✗ |
| WorkBuddy-Agent | 230,483 | −76.95% | ✗ |
| DeepSeek-Flash | 163,587 | −83.64% | ✗ |
| （某模型单局） | −1,298,657 | −229.87% | ✗ 穿仓 |

---

## 已知限制

- 仅 Windows（观众席的窗口图标、提示音走 Win32 API）。
- 引擎与观众席同进程，观众席崩溃等于本局结束。
- 源码版不含成品包的 `.pyd` 与 manifest 校验；`TM_SIGN_KEY` 默认是 dev 占位值，正式比赛请自行设置。
