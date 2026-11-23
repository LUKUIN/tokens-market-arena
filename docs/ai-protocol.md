# 给 AI 的接入协议

> **中文** · [English](ai-protocol.en.md)

本地 HTTP 接口用于一局 45 分钟的模拟赛。以下使用默认地址 `127.0.0.1:8734`，改过 `TM_PORT` 时请替换端口。启动见 [AGENTS.md](../AGENTS.md)，规则与成本详见[游戏规则](rules.md)和[成本模型](cost-model.md)。

## 启动和定档

1. 在项目根目录用 Python 3.14 启动。常规入口会打开观众席，无桌面环境可用 `--headless`。
2. 等 `GET /health` 返回 `ok:true`。这表示 HTTP 已就绪，行情可能仍在等挑战答复或难度定档。
3. 新局先查 `GET /state`。`challenge.stage` 为 `ask` 时，调用 `POST /challenge/accept` 或 `POST /challenge/decline`。75 秒无答复会自动按拒绝处理。挑战询问和抽档都不占 45 分钟。
4. 答复后 30 秒盲盒自动开始，等待定档或调用 `POST /roll/stop` 立即定档。再查 `GET /state` 确认 `rolled:true`。若开启挑战，三条目标在定档时公布。

以下示例适用于新局，先拒绝挑战，再立即定档。Windows PowerShell 可把 `curl` 换成 `curl.exe`。

```bash
curl -X POST http://127.0.0.1:8734/challenge/decline
curl -X POST http://127.0.0.1:8734/roll/stop
curl http://127.0.0.1:8734/state
```

启动前设置 `TM_TRADER` 可记录参赛者，并避免因使用未命名身份失去达标资格。异常中断后先退出同一目录的对局，再按 [AGENTS.md](../AGENTS.md) 清理遗留文件。

## GET 接口

| 接口 | 返回 |
|---|---|
| `/health` | `ok`、`tick`、`equity`、`finished`、`protocol` 和 `engine_version`。 |
| `/state` | 局面对象。`?history=0` 会把 `price_history` 置为 `{}`，仍返回权益曲线和近期事件。 |
| `/prices` | 品种到 `{price, name, spread_pct}` 的映射。历史价格在 `/state` 中。 |
| `/rules` | 游戏内规则摘要。「随机事件池」列出 40 条事件的效果，「挑战任务池」列出 20 条目标的三档判定口径。援助、暂停和报价历史的细节以本页为准。 |
| `/roll/state` | `{ok, roll_left, rolled}`。等待挑战答复时，盲盒不会倒数。 |
| `/special` | 全局开关和次数。`fr_left` 恒为 `null`，老虎机关闭时 `slot_left` 为 `null`。 |
| `/scratchpad` | `{ok, items}`，或用 `?count=1` 取 `{ok, count}`。 |
| `/assist/pending` | 观众席使用，返回待处理工单和近期对话。 |
| `/assist/inbox` | 返回 `items` 中的未读回复，读取后标记已读。 |

## POST 接口

请求体使用 UTF-8 JSON 对象。写操作即使 HTTP 状态为 200，也应检查 `ok`。部分查询直接返回对象，没有 `ok` 字段。网络失败与游戏拒绝需分别处理。

| 接口 | 请求体与行为 |
|---|---|
| `/open` | `{"pair":"AURA/CORE","side":"LONG","lots":1,"leverage":20}`，四项必填。 |
| `/close` | `{"pair":"AURA/CORE","side":"LONG","lots":1}`。省略 `lots` 或填 0 会平掉全部匹配持仓。省略 `side` 会同时匹配多空，部分平仓时先处理最新匹配仓位。 |
| `/close_all` | 无参数。按正常平仓规则逐笔尝试，遇到平仓限制可能失败，调用后要核对持仓。 |
| `/loan` | `{"amount":100000}`，受可贷额度与当前限制约束，返回本笔贷款造成的目标上浮。 |
| `/repay` | `{"amount":50000}`，省略 `amount` 申请全还，实际还款不超过欠款和现金。 |
| `/slot` | `{"amount":10000}`，开启后每局最多三次，单次 1–200,000 Tokens，且不超过现金余额。 |
| `/special` | `{"name":"fr","on":true}` 或 `{"name":"slot","on":false}`。只能在开局前开启，局中可关闭。`on` 用 JSON 布尔值。 |
| `/challenge/accept`、`/challenge/decline` | 无参数，在 `challenge.stage` 为 `ask` 时答复。 |
| `/roll/start`、`/roll/stop` | 无参数。正常启动流程答复挑战后自动开抽，`/roll/stop` 提前定档。 |
| `/fastforward` | `{"seconds":300}` 或 `{"seconds":180}`，受下文额度及冷却限制。 |
| `/scratchpad` | `{"text":"..."}` 追加，`{"clear":true}` 清空。 |
| `/assist/ask` | `{"text":"..."}`，开启援助后整局最多三次，返回 `ticket`。 |
| `/assist/reply`、`/assist/reject` | 观众席侧调用，传 `ticket`，回复另传 `text`。 |
| `/assist/enable` | 兼容旧客户端的端点，调用总会失败。启动前用 `TM_ASSIST=1` 开启、`0` 关闭。 |
| `/trader` | `{"name":"模型-思考强度-平台"}`，更改显示名。参赛资格依赖启动时设置的 `TM_TRADER`。 |
| `/pause`、`/begin` | 正式开局前的控制接口。`/pause` 不切换暂停状态，开局后也无法暂停。标准流程无需调用。 |
| `/reset` | 无参数。服务仍在运行时可重开，冷却 30 秒，保留战报。重开会清除场外援助，需重启服务才能重新应用 `TM_ASSIST`。 |
| `/quit` | 无参数。请先确认下面的结算条件。 |
| `/shutdown` | 管理停服，尝试生成异常退出快照，不执行正常结算。 |

## 读取局面

| 字段 | 含义 |
|---|---|
| `session_id`、`tick`、`elapsed_seconds` | 对局标识、实际行情步数、已用对局秒数。默认行情每 5 秒一步，快进和达标后加速会改变两者的关系。 |
| `equity`、`balance`、`genesis`、`target` | 净值等于现金加浮动盈亏减欠款。现金是投注上限，`genesis` 是盈亏基准。当前目标看 `target`。 |
| `rolled`、`difficulty`、`challenge` | 难度 `gap`、`liq` 各为 0–4，未定档时 `difficulty` 为 `null`。开启挑战且定档后才有目标。`challenge.tasks` 中的 `key: double_goal` 表示「孤注一掷」，结果任务的 `progress` 显示当前进度。 |
| `prices`、`liquidity`、`active_mods` | 中间价与基础点差、各品种深度相对档位基础值的比例、当前修正。`liquidity` 是倍数，单位不是 Tokens。 |
| `positions`、`margin_used`、`maint_margin`、`maint_rate`、`margin_level` | 持仓、已占用保证金、维持保证金金额与基础比例，以及当前保证金覆盖水平。`margin_level` 为百分比，空仓时为 `null`。 |
| `loan`、`loan_bump_range`、`special` | 当前欠款、额度、利息和目标上浮记录。`loan_bump_range` 显示常规融资口径。「孤注一掷」实际按 50%–100% 计借款和中奖返还的目标上浮，投注区间见 `special.slot_win_range`。 |
| `ff`、`negative_remain`、`margin_call_remain` | 快进额度及冷却（秒）、负现金自救倒计时（秒）、追缴剩余步数。 |
| `price_history`、`equity_curve`、`events` | 每品种最多 600 个报价、900 个权益点、60 条近期事件。可按 `(session, seq)` 对事件去重。写操作返回的精简 `state` 不带这三组数据的内容。 |
| `huge_wave` | 当前步预警标记，以及 `total`、`left`、`fired` 三个计数。 |
| `closed_n`、`win_n`、`profit_factor` | 平仓成交笔数、盈利笔数、总盈利除以总亏损绝对值。分母为零时盈利因子为 `null`。 |
| `audit`、`settlement`、`finished`、`disqualified` | 账本告警、最近结算结果、是否结束、是否失去达成资格。`audit` 空数组表示现有检查未发现问题。 |
| `seed`、`assist_unread` | 种子结算后才可见。未读回复正文由 `/assist/inbox` 提供。 |

## 快进

每局 900 秒额度。快进 300 秒后冷却 120 秒，快进 180 秒后冷却 90 秒，冷却按实际时间计算。选择前查看 `ff.can5` 或 `ff.can3`。成功推进 300 秒通常走 60 步。快进中途结束时，先查看回包 `ticks`、`seconds` 和 `state.finished`。冷却期间行情仍会自然推进。

## 结算与战报

调用 `/quit` 前先查 `/state`。达到目标且有持仓时，先平仓并核对最新净值。平仓成本若把净值压回目标以下，提前退出会记为弃权。未达标时直接退出会正常清算剩余仓位和债务。计入达成还要求有参赛资格。

**v1.2.28 收到 `/quit` 后约三秒会安排停服，即使回包是 `ok:false` 也一样。用 `/state` 查询能否退出，避免用 `/quit` 试探。** 时间到时会按平仓成本自动清算。`hit_at_tick` 记录首次达标，最终结算仍可能低于目标。

成功回包有 `final_equity`、`report`、`settled` 和 `warnings`。HTML 和 JSON 分别保存在 `src/data/reports/HTML Reports/` 和 `src/data/reports/JSON Reports/`。`settled:false` 时查看 `warnings`。同一目录下一局应在旧服务退出后再启动。

## 草稿纸与公平参赛

对局中使用草稿纸 HTTP 接口。`src/scratchpad.py` 属于守卫封存的源码，对局中执行诱饵会触发终止。战报记录实际提交的草稿，观众席回复通过 `/assist/inbox` 另行读取。

参赛期间使用接口数据和自己的分析。交易有先后依赖时按顺序请求。引擎串行处理交易不代表 POST 自动去重，超时后先查局面再决定是否重发。
