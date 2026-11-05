# 给 AI 的接入协议

> **中文** · [English](ai-protocol.en.md)

这个游戏的 HTTP 接口是**为一件事设计的：让大模型用最少的 token 理解局面并做出决策**。

> **什么算 Bug 反馈**：接口返回与文档不符、数值自相矛盾、程序崩溃、数据明显损坏。
> 除此之外——难度抽签、是否借款、何时止损、要不要玩老虎机——都在游戏内部由参赛方决定。

## 零、开始之前：必读与禁止

### 前置要求

1. **先读完本仓库所有 `.md` 文件**（`README.md` + `docs/` 下每一篇），理解规则、接口和成本模型之后再动手。
   不要边玩边查——那会让你的决策被规则细节牵着走。
2. **必须开着观众席启动**：用 `python run.py`（可加 `--interactive` 之外不要加参数），
   人类要能在屏幕上看到这一局的实时权益、持仓和活动流。
   `run.py server` 是**无头模式**，没有窗口，只允许在确实没有桌面的环境里用。
   无头起的对局事后仍可观看：`只开观众席.bat`（或 `python run.py spectator`）会挂到它上面，
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
  **只要你的输入来自游戏接口**（`/rules`、`/state`、`/prices`、`/events`）。
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
set TM_FR=1            # 金融回逆（整局借款 2 次，目标区间 -20%~100%）
set TM_SLOT=0          # 老虎机（整局 3 次，80% 空 / 15% 5 倍 / 5% 10 倍）
python run.py
```

> **全程不会提问。** 所有配置都来自环境变量，没设置的用默认值
> （`TM_TRADER=访客`、`TM_EVENTS=0`、`TM_FR=0`、`TM_SLOT=0`）。
> 启动顺序：起服务 → 30 秒难度盲盒 → 计时开始。两个全局开关在起服务之前读入。

### 可写目录

项目根目录下的 `_agent/` 是可写工作区。它的**内容**会在每条退出路径上被清空——新一局开始前、
`/quit` 结算时、超时结算时、`/reset` 时——目录本身保留。`.gitignore` 已忽略它，写进去的东西
不会进入版本库。

这条清理只管 `_agent/`。写在别处（项目根、`src/`）的文件不在其覆盖范围内：`deep-clean.ps1`
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
| GET | `/health` | 存活检查，返回 tick / equity / finished |
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

### 控制

| 方法 | 路径 | 说明 |
|---|---|---|
| POST | `/tick` | 手动推进 1 tick（**扣快进额度、受冷却**） |
| POST | `/fastforward` | `{"seconds":300}`，档位只能是 300 或 180 |
| POST | `/roll/start` | 启动盲盒 |
| POST | `/roll/stop` | 定格难度 |
| POST | `/begin` | 解除开局冻结 |
| POST | `/pause` | 冻结（**只在开局前有效，之后一律拒绝**） |
| POST | `/scratchpad` | `{"text":"..."}`，写草稿纸 |
| GET | `/special` | 两个全局开关状态 + 剩余次数 |
| POST | `/special` | `{"name":"fr"或"slot","on":true}`，切换开关（局内开启扣 30 万现金） |
| POST | `/slot` | `{"amount":10000}`，老虎机下注（1~200000，≤当前权益，整局 3 次） |
| POST | `/reset` | 开新一局 |
| POST | `/quit` | 主动结算并生成报告 |
| POST | `/shutdown` | 关服务（**会记一次异常退出**） |

## 四、`/state` 里最该看的字段

> **省 token 的用法**：`GET /state?history=0` 会省掉 `price_history`（每品种最多
> 2000 个点，随对局膨胀）。下单类接口（`/open` `/close` `/loan` `/tick` 等）的回包
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

  "active_mods": ["央行放水"],          // 当前生效的事件名
  "loan_bump_range": [1.0, 100.0],      // 借款上浮区间（%）：未开金融回逆 [1,100]，已开 [-20,100]
  "special": {                          // 两个全局开关
    "fr": true, "fr_left": 2,           // 金融回逆已开，还剩 2 次借款
    "slot": false, "slot_left": 3,      // 老虎机未开
    "slot_win": 0.0, "fr_lo_pct": -20.0 // 老虎机累计返还 / 借款下限（%）
  },
  "seed": 20261105,                     // 本局随机种子（写进报告，可复现）

  "gap_level": "低", "liq_level": "正常",
  "ff_remain": 900,                     // 快进剩余额度（秒）
  "finished": false,
  "events": [ ... ]                     // 最近事件，含完整文案
}
```

### 七个判断点

1. **`equity` vs `target`** —— 还差多少
2. **`margin_level`** —— 低于 100% 要补保证金，低于 50% 会被强平
3. **`active_mods`** —— 现在有什么临时规则在改行情
4. **`loan_bump_range`** —— 现在借钱是什么代价（`[1,100]` 正常，`[-20,100]` 是金融回逆）
5. **`special`** —— 两个开关开没开、还剩几次（`fr_left` / `slot_left`）
6. **`ff_remain`** —— 还能快进多少秒
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

**`/tick` 也受同一套额度和冷却约束** —— 防止 AI 把 45 分钟压缩成 5 分钟。

## 六、草稿纸（可选）

记录你的判断依据。结算时会合并进 HTML 报告，让人看到「你为什么这么操作」。

```bash
curl -X POST http://127.0.0.1:8734/scratchpad \
     -H "Content-Type: application/json" \
     -d '{"text":"t120 看到 AURA 偏离均值 8%，做空"}'
```

也可以不依赖服务：

```bash
python src/scratchpad.py --list
```

**注意**：Git Bash 的 `curl -d` 会把中文转成 GBK，服务端解不了。要么用 Python 发请求，要么先用英文写。

## 六点五、提前结束要不要紧

`POST /quit` 是**正常结算**，不是异常退出：

- 立刻平掉所有持仓、结清贷款、生成完整报告
- 最终权益按那一刻计算，评级、成本归因、明细照常生成
- **不扣分、不标记异常、不影响之后开新局**
- 与「45 分钟时间到」的唯一区别是报告里结束原因写「主动结束」

真正的异常退出只有两种：`POST /shutdown`（立即停服，留「未结算」标记）和进程被强杀。

所以如果你对当前成绩满意，提前结束是安全的；代价只是放弃剩余时间里可能继续赚到的收益。

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
