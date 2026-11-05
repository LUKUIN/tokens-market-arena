# Tokens 交易市场 · 参赛者入口

单文件启动说明。读完这一页就能开局；规则从接口读，不必逐个翻 `docs/`。

一局 45 分钟：初始权益 **1,000,000 Tokens**，目标 **2,000,000**。行情、事件、跳空全部是程序生成的虚构数据，与任何真实市场无关。

## 1. 启动

```bash
cd <项目目录>

TM_TRADER="<模型名-思考强度-平台>" \
TM_EVENTS=1 TM_FR=1 TM_SLOT=1 TM_ASSIST=1 \
  nohup python run.py server > run.log 2>&1 &

# 就绪检测：启动需要 3~8 秒，固定 sleep 会假失败
for i in $(seq 1 30); do
  curl -sf http://127.0.0.1:8734/health >/dev/null 2>&1 && break
  sleep 1
done
```

`run.py server` 是无头模式。`python run.py`（不带 `server`）会额外弹一个只读观众席窗口，没有桌面环境时创建窗口失败会带崩进程。

| 变量 | 作用 |
|---|---|
| `TM_TRADER` | 参赛标识，格式 **模型名-思考强度-平台**，例 `Doubao-1.5-pro-深度思考-扣子`；原样写进报告文件名与正文 |
| `TM_EVENTS` | `1` 开启随机事件（含黑天鹅跳空），`0` 只有黑天鹅 |
| `TM_FR` | `1` 开启【金融回逆】：整局可借款 2 次 |
| `TM_SLOT` | `1` 开启【老虎机】：整局 3 次 |
| `TM_ASSIST` | `1` 开启【外部的怜悯】：整局可向观众席求助 3 次 |
| `TM_PORT` | 服务端口，默认 `8734` |

## 2. 定档

难度是开局抽的，未定档时 `/tick` 不推进。

```bash
curl -X POST http://127.0.0.1:8734/roll/stop
```

## 3. 开局读这两样

| 接口 | 内容 |
|---|---|
| `GET /rules` | 全部规则：交易细则、事件表、费率、完整接口清单 |
| `GET /state` | 当前局面：权益、持仓、报价、盘口深度、事件流 |

拿到这两个之后，参赛过程中不需要再读任何 Markdown。

## 4. 结算

```bash
curl -X POST http://127.0.0.1:8734/quit
```

HTML 报告写到 `src/data/reports/`。

## 边界

- 对局期间 `src/*.py` 被封存成诱饵。读到的是假文件，执行或 import 它会写入作弊标记并直接终止对局
- 观众席只能在你主动求助（`POST /assist/ask`）之后回复，不能主动发消息，也不能替你下单
- 求助整局 3 次上限；局内开通要花 500,000 现金，由参赛者自己决定，观众席界面上没有开通入口

## 分册文档

`docs/rules.md`、`docs/ai-protocol.md`、`docs/cost-model.md` 是上述内容的分册展开版，供人类查阅。参赛期间以 `GET /rules` 的返回为准。
