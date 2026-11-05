# 给 AI 的接入协议

这个游戏的 HTTP 接口是**为一件事设计的：让大模型用最少的 token 理解局面并做出决策**。

## 一、启动流程

```bash
# 1. 清掉上一局残留（有对局在跑时不要这么做）
#    data/session.json、.running、.seal、.watch.pid、.rules_ack 删掉即可

# 2. 非交互启动（不读 stdin，适合后台）
set TM_TRADER=MyAgent
set TM_EVENTS=1        # 随机事件
set TM_FR=1            # 金融回逆（整局借款 2 次，目标区间 -20%~100%）
set TM_SLOT=0          # 老虎机（整局 3 次，70% 空 / 25% 10 倍 / 5% 20 倍）
python run.py ai
```

> **问答顺序是固定的**：玩家名 → 随机事件 → 老虎机/金融回逆 → 起服务 → 30 秒难度盲盒。
> 两个全局开关在「随机事件」之后、「抽难度」之前决定。
> 四个变量都给了才完全不问；缺哪个 `run.py` 就会交互问哪个（`input()` 读到 EOF 时取默认值「关」）。

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
| POST | `/close` | `{"pair":"AURA/CORE","lots":10}` |
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
| POST | `/slot` | `{"amount":10000}`，老虎机下注（1~100000，≤当前权益，整局 3 次） |
| POST | `/reset` | 开新一局 |
| POST | `/quit` | 主动结算并生成报告 |
| POST | `/shutdown` | 关服务（**会记一次异常退出**） |

## 四、`/state` 里最该看的字段

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

## 六、草稿纸（可选但推荐）

记录你的判断依据。结算时会合并进 HTML 报告，让人看到「你为什么这么操作」。

```bash
curl -X POST http://127.0.0.1:8734/scratchpad \
     -H "Content-Type: application/json" \
     -d '{"text":"t120 看到 AURA 偏离均值 8%，做空"}'
```

也可以不依赖服务：

```bash
python src/TokensMarket.py scratchpad --list
```

**注意**：Git Bash 的 `curl -d` 会把中文转成 GBK，服务端解不了。要么用 Python 发请求，要么先用英文写。

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
