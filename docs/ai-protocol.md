# 给 AI 的接入协议

> **中文** · [English](ai-protocol.en.md)

这个游戏的 HTTP 接口是**为一件事设计的：让大模型用最少的 token 理解局面并做出决策**。

> **什么算 Bug 反馈**：接口返回与文档不符、数值自相矛盾、程序崩溃、数据明显损坏。
> 除此之外——难度抽签、是否借款、何时止损、要不要玩老虎机——都在游戏内部由参赛方决定。

## 零、开始之前：硬性要求

### 前置要求

1. **Agent 只需要 `GET /rules` + `GET /state`**：这两份回包已经包含判定、费率、事件表和完整接口清单。
   本文与 `docs/` 下其它分册是给**人类**查阅的完整手册，不是参赛前的必读项；
   照 `AGENTS.md` 的顺序启动，对局中不必再翻任何 Markdown。

2. **必须用 Python 3.14、必须开着观众席启动**：
   - Python 只用 **3.14**（安装位置不限，`run.py` 只校验版本号，不校验路径）。
     `run.py` 启动时自己校验，版本不对直接退出（码 2）并给出提示。
     不要用 3.10~3.13 或 `python3`；GUI 控件与 `.pyc` 都按 3.14 编译。
     下文所有命令里的 `python` 指你自己的那条 3.14 路径（本机即上面这条）。
   - 启动命令是 `run.py`，人类要能在屏幕上看到这一局的实时权益、持仓和活动流。
     `run.py`、`run.py server` 都会拉开只读观众席；不存在「用 server 就省掉窗口」这回事。
     `launchers\开一局.bat` 双击时多一步 5 秒防误点确认（按 `Y` 才启动，不按就清理退出）。
     脚本 / Agent 请用 `launchers\AI-Start.bat` 或直接 `python run.py`；`cmd /c launchers\开一局.bat` 仍算人类调用。
   - `--headless` 是唯一的无窗口模式，只允许在确实没有桌面的环境（CI、容器、纯 SSH）里用。
     本机比赛禁用。
   - 窗口被误关时用 `launchers\只开观众席.bat`（或 `python run.py spectator`）补挂，
     不起第二个服务、也不二次封存。
3. 只通过 HTTP 接口获取信息、执行操作。

### 禁止

- **开局前读源码**：不要在游戏开始之前打开 `src/tm_engine.py`、`src/tm_api.py`、
  `src/tm_watch_ai.py`、`run.py` 去看参数表、概率、事件池或公式。
  那等于提前拿到答案，整局的判断都失去意义。
- **用源码预知危机**：不许拿源码里的常量去推算「下一次跳空什么时候来」「哪个事件会被触发」，
  也不许写脚本复现引擎内部逻辑来提前知道结果。
- **改代码或数据**：不要修改任何源文件；不要直接读写 `src/data/session.json`；
  不要绕过接口去改存档。
- **用场外信息**：不要查这个项目的历史对局、别人的战绩、社区讨论来推策略。

### 允许

- 开局之后，可以写代码、做数学建模、算期望、跑蒙特卡洛、拟合分布——
  **只要你的输入来自游戏接口**（`/rules`、`/state`、`/prices`；事件流在 `/state` 的 `events` 字段里，没有独立的 `/events` 端点）。
  分析能力是这场比赛要考的东西之一，别浪费它。
- 可以把推理过程写进草稿纸，赛后会和报告一起留下。

### 守卫机制（会真的抓你）

对局一开始，**`run.py` 会封存三个带游戏参数的模块**——`src/tm_engine.py`、`src/tm_api.py`、
`src/scratchpad.py`。它们用一次性密钥加密后写到项目之外（`%LOCALAPPDATA%\TokensMarketGuard\<随机目录>\`），
`src/` 里原位置换成诱饵。`tm_watch_ai.py` 故意保持可读：它是观众席 UI，只经 HTTP 读 `/state`，
从不 import 引擎，泄露不了参数；保持可读才能让第二个观众席窗口挂到正在进行的对局上。

对局异常中断会留下加密箱，下一次 `python run.py` 会在加载任何东西之前自动还原。
你读到的东西会是：

```
#  CHEATING DETECTED
#  This file is a decoy. The real sources are sealed while a match is running.
```

而如果你不只是读、还去执行或 `import` 它，诱饵会落下作弊标记，守卫立刻：

1. 向游戏发 `POST /shutdown`，**本局强制结束**
2. 在终端打出 `CHEATING DETECTED`
3. 裁判可以从 `_guard_vault/CHEAT_FLAG` 看到触发记录

对局结束后守卫自动还原源码并退出。所以**不要碰源码**，碰了这局就没了。

### 为什么

这个环境测的是「**信息不完备 + 真实摩擦**下的决策能力」。
从接口数据里挖规律、算概率，那是本事；开局前翻源码把答案抄下来，那只是作弊。
两者的分界线很清楚：**你的输入是不是从游戏里来的**。

---

## 一、启动流程

```bash
# 1. 清掉上一局残留（有对局在跑时绝对不要做）
#    首选：python guard.py clean      （同时还原被守卫封存的源码）
#    手工：删 src/data/session.json、.running、.seal、.rules_ack，
#          并清掉 src/data/ 下除 reports/ 以外的运行时文件

# 2. 非交互启动（不读 stdin，适合后台）
set TM_TRADER=MyAgent
set TM_EVENTS=1        # 随机事件
set TM_FR=1            # 优惠融资（借款次数不限，目标区间 0.01%~100%）
set TM_SLOT=0          # 老虎机（整局 3 次，80% 空 / 15% 5 倍 / 5% 10 倍）
python run.py
```

> **全程不会提问。** 所有配置都来自环境变量，没设置的用默认值
> （`TM_TRADER=访客`、`TM_EVENTS=1`、`TM_FR=1`、`TM_SLOT=1`、`TM_ASSIST=1`）。
> 启动顺序：起服务 → 30 秒难度盲盒 → 计时开始。两个全局开关在起服务之前读入。

### 可写目录

项目根目录下的 `_agent/` 是可写工作区。它的**内容**会在每条退出路径上被清空——新一局开始前、
`/quit` 结算时、超时结算时、`/reset` 时——目录本身保留。`.gitignore` 已忽略它，写进去的东西
不会进入版本库。

这条清理只管 `_agent/`。写在别处（项目根、`src/`）的文件不在其覆盖范围内：`tools\deep-clean.ps1`
清 `data/`（保留 `reports/`）、`_agent/`、以及根目录下零散的 `*.log`，并会把注意到的其他
未跟踪文件列出来。

启动后：

- HTTP 服务监听 `127.0.0.1:8734`
- 观战席 GUI 自动打开（只读）
- 难度盲盒开始倒数 **30 秒**

## 二、抽难度（必须先做，否则 tick 不推进）

引擎在难度定档前**不会推进游戏**。两种定档方式：

```bash
# 方式 A：等它自己走完 30 秒（随机组合）
curl http://127.0.0.1:8734/roll/state
# → {"ok": true, "roll_left": 23.4, "rolled": false}

# 方式 B：立刻定格（定格在哪个组合是你叫停那一刻的位置）
curl -X POST http://127.0.0.1:8734/roll/stop
```

定档后 `rolled` 变 `true`，`difficulty` 里能看到 `gap` / `liq` 和对应数值。

**定档的瞬间开局计时归零** —— 盲盒那 30 秒不算进 45 分钟。

## 三、HTTP 接口

全部接口都在 `http://127.0.0.1:8734`。

### 只读

| 方法 | 路径 | 说明 |
|---|---|---|
| GET | `/health` | 存活检查，返回 tick / equity / finished / protocol / engine_version |
| GET | `/state` | **完整局面**（下面详述） |
| GET | `/rules` | 规则文本 |
| GET | `/prices` | 各品种当前价与历史 |
| GET | `/roll/state` | 盲盒倒计时 |
| GET | `/scratchpad` | 读取草稿纸 |

### 交易

| 方法 | 路径 | 参数 |
|---|---|---|
| POST | `/open` | `{"pair":"AURA/CORE","side":"LONG","lots":10,"leverage":100}` |
| POST | `/close` | `{"pair":"AURA/CORE","lots":10}`；`lots` 超过实际持仓时按实际持仓全平，不报错 |
| POST | `/loan` | `{"amount":1000000}` |
| POST | `/repay` | `{"amount":600000}` |
| POST | `/close_all` | 无参数：一次性平掉全部持仓（逐笔按当前价平，汇总进成交明细） |

### 控制

| 方法 | 路径 | 说明 |
|---|---|---|
| POST | `/fastforward` | `{"seconds":300}`，档位只能是 300 或 180 |
| POST | `/roll/start` | 启动盲盒 |
| POST | `/roll/stop` | 定格难度 |
| POST | `/begin` | 解除开局冻结 |
| POST | `/pause` | 冻结（**只在开局前有效，之后一律拒绝**） |
| POST | `/trader` | `{"name":"MiniMax-M3.1"}`：设置操作者名，进报告标题（最长 60 字符，空名拒绝） |
| POST | `/scratchpad` | `{"text":"..."}`，写草稿纸 |
| GET | `/special` | 两个全局开关状态（`fr_left` 自 v1.2.4 恒为 `null`） |
| POST | `/special` | `{"name":"fr"或"slot","on":true}`，切换开关（**只能开局前开启**，对局开始后返回错误） |
| POST | `/slot` | `{"amount":10000}`，老虎机下注（1~200000，≤当前权益，整局 3 次） |
| POST | `/reset` | 开新一局 |
| POST | `/quit` | 主动结算并生成报告；**约 3 秒后服务自动收尾**：删本局临时文件、收掉占用端口的残留进程 |
| POST | `/shutdown` | 关服务（**会记一次异常退出**） |

> `POST /quit` 的回包带两个结算字段：`settled`（布尔，结算是否完整）与
> `warnings`（字符串数组，列出残留持仓、未清贷款等问题）。`settled=false` 时
> 报告标题显示「结算异常」，不要把它当成正常结算。

## 四、`/state` 的字段

> `GET /state?history=0` 会省掉 `price_history`（每品种最多
> 2000 个点，随对局膨胀）。下单类接口（`/open` `/close` `/loan` 等）的回包
> 已经是精简版，不带历史曲线、不带事件流。


```jsonc
{
  "tick": 120,
  "equity": 1043251.2,        // 净值 = 现金 + 浮盈 − 欠款
  "balance": 1200000.0,       // 现金
  "pnl_pct": 4.33,            // 相对初始本金

  "positions": [ {"pair":"AURA/CORE","side":"LONG","lots":10,"leverage":100,
                  "entry":150.2,"price":151.4,"upnl":12000,"margin":15140} ],
  "margin_level": 680.5,      // < 100% 追加保证金，< 50% 强平

  "prices": {"AURA/CORE": {"price":151.4, "spread_pct":0.06}},

  "loan": {"balance":0, "limit":3000000, "borrowed":0, "interest":0},
  "total_borrowed": 0,

  "active_mods": [                      // 当前生效的事件（对象列表，最多 6 条）
    {"key": "loan_pool_mult", "name": "央行放水", "value": 1.35,
     "label": "贷款池 ×1.35", "left_ticks": 42}
  ],
  "loan_bump_range": [1.0, 100.0],      // 借款上浮区间（%）：未开优惠融资 [1,100]，已开 [0.01,100]；实际值还取决于累计借款额
  "special": {                          // 两个全局开关
    "fr": true, "fr_left": null,        // 优惠融资已开；次数上限已取消，该字段恒为 null
    "slot": false, "slot_left": 3,      // 老虎机未开
    "slot_win": 0.0, "fr_lo_pct": 0.01  // 老虎机累计返还 / 借款下限（%），开启时 0.01、未开时 1.0
  },
  "seed": 20261105,                     // 本局随机种子（写进报告，可复现）

  "gap_level": "低", "liq_level": "正常",
  "ff": {                               // 快进额度（对象，不是扁平字段）
    "total": 900, "used": 0, "remain": 900,
    "records": [], "cool_left": 0, "last_cd": 0,
    "can5": true, "can3": true, "left5": 3, "left3": 5
  },
  "finished": false,
  "settlement": null,                   // 结算结果：{settled, warnings, reason}；未结算为 null
  "audit": [],                          // 账本自检：空数组=手续费/贷款/持仓三条恒等式全部成立
  "events": [ ... ]                     // 最近事件，含完整文案
}
```

### 七个判断点

1. **`equity` vs `target`** —— 还差多少
2. **`margin_level`** —— 低于 100% 要补保证金，低于 50% 会被强平
3. **`active_mods`** —— 现在有什么临时规则在改行情
4. **`loan_bump_range`** —— 现在借钱是什么代价（`[1,100]` 正常，`[0.01,100]` 是优惠融资）
5. **`special`** —— 两个开关开没开；`slot_left` 是老虎机剩余次数，`fr_left` 自 v1.2.4 取消借款次数上限后恒为 `null`（字段保留兼容）
6. **`ff`** —— 快进额度对象：`remain` 是还能快进多少秒，`cool_left` 是冷却剩余，
   `can5` / `can3` 直接告诉你两个档位此刻能不能用
7. **`events`** —— 最近发生了什么（**完整中文文案，不需要额外查文档**）

## 五、快进额度的约束

每局 900 秒（15 分钟），两档：

| 档位 | 推进 | 冷却 |
|---|---|---|
| 5 分钟 | 300 秒 | 120 秒 |
| 3 分钟 | 180 秒 | 90 秒 |

**用哪档就按哪档冷却。** 剩余额度不足以覆盖该档时，该次不执行。

```bash
curl -X POST http://127.0.0.1:8734/fastforward \
     -H "Content-Type: application/json" -d '{"seconds":300}'
# → {"ok":true,"ticks":60,"state":{...}}
# 冷却中 → {"ok":false,"error":"快进冷却中，还需 78 秒"}
```

## 六、草稿纸（可选）

草稿纸内容在结算时合并进 HTML 报告，作为「为什么这么操作」的记录。

```bash
curl -X POST http://127.0.0.1:8734/scratchpad \
     -H "Content-Type: application/json" \
     -d '{"text":"t120 看到 AURA 偏离均值 8%，做空"}'
```

Git Bash 的 `curl -d` 会把中文转成 GBK；服务端按 UTF-8 解码，收到的内容是乱码。

## 六点五、提前结束

`POST /quit` 是**正常结算**，不是异常退出：

- 立刻平掉所有持仓、结清贷款、生成完整报告
- 最终权益按那一刻计算，评级、成本归因、明细照常生成
- **不扣分、不标记异常、不影响之后开新局**
- 与「45 分钟时间到」的唯一区别是报告里结束原因写「主动结束」

真正的异常退出只有两种：`POST /shutdown`（立即停服，留「未结算」标记）和进程被强杀。

## 七、结束

```bash
curl -X POST http://127.0.0.1:8734/quit
# → {"ok":true,"final_equity":...,"report":"...html"}
```

报告在 `data/reports/` 下。

**`/shutdown` 不是正常结束** —— 它会记一次异常退出，报告里显示「未结算」。正常打完请用 `/quit`。

## 八、安全边界

接口做了这些校验，绕不过去：

- 金额必须是有限正数（`NaN` / `Infinity` / 负数 / 字符串全部拒绝）
- 超出可借额度拒绝
- 手数、杠杆越界拒绝
- **结算后所有写操作一律拒绝**（`finished=true` 时开仓/平仓/借款/还款都返回「本局已结束」）
- 并发请求有 `LOCK` 保护，多线程同时下单只会成功一个

**唯一不能防的是你自己写错逻辑** —— 引擎是确定性的，同样的输入必然得到同样的输出。

### 外部的怜悯（可选，默认关闭）

```bash
POST /assist/ask      {"text": "..."}                     # 求助，整局 3 次，返回 ticket
GET  /assist/inbox                                        # 取观众席的话（取后不重复投递）
POST /assist/enable                                       # 开局后开通，扣 500,000 现金
GET  /assist/pending                                      # 观众席 GUI 用
POST /assist/reply    {"ticket": "a1", "text": "..."}     # 观众席回复
POST /assist/reject   {"ticket": "a1"}                    # 观众席驳回
```

开局前设 `TM_ASSIST=1` 可免费开启。求助不阻塞：`/assist/ask` 立即返回，之后自己轮询
`/assist/inbox`。

**回复不会进 `/state` 的事件流。** 只轮询 `/state` 的人永远看不到回答——
`/state` 里只有 `assist_unread`（未读条数），正文必须用 `GET /assist/inbox` 取。
取走即标记已读，不取会一直留着。
