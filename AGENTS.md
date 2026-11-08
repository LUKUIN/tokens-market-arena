# Tokens 交易市场 · 参赛者入口

单文件启动说明。读完这一页就能开局；规则从接口读，不必逐个翻 `docs/`。

一局 45 分钟：初始权益 **1,000,000 Tokens**，目标 **2,000,000**。行情、事件、跳空全部是程序生成的虚构数据，与任何真实市场无关。

## 0. 用哪个 Python（硬要求，不要自己找）

只用这一条，**Python 3.14.7**：

```
C:\Users\User\AppData\Local\Programs\Python\Python314\python.exe
```

`run.py` 启动第一件事就是校验版本：不是 3.14 直接中止，并把上面这条命令打出来。
不要用 `where python`、`py -3.12`、`python3` 去另找一个解释器——观众席的 GUI 控件和 `.pyc`
都是按 3.14 编译的，换成别的版本必然起不来。找不到命令时直接写全路径，不要报「环境有问题」。

## 1. 检查上一局残留（有则清，无则直接开始）

**正常打完一局时，这一步什么都不用做**：结算完成后 `run.py` 会自己删掉临时文件、收掉相关进程，
`src/data/` 下只会剩下 `reports/`。只有手动中断、进程崩溃、或窗口没关干净时才需要动手。

先看一眼，有没有残留一看便知：

```bash
cd <项目目录>
ls -A src/data/ | grep -v '^reports$' | grep -q . && echo "有残留，需要清理" || echo "干净，直接进第 2 步"
```

**显示「干净」就跳过本节，直接启动。** 显示「有残留」时再执行：

```bash
# 上一局服务可能还占着端口：先重置再停服（/reset 会清 data/ 下除 reports/ 外的文件）
curl -s -X POST http://127.0.0.1:8734/reset    >/dev/null 2>&1 || true
curl -s -X POST http://127.0.0.1:8734/shutdown >/dev/null 2>&1 || true

# 服务没跑时直接删存档
rm -f src/data/session.json src/data/.scratchpad.jsonl
rm -rf src/data/_agent
```

**不要删 `src/data/reports/`** —— 那是历史战报，每局结算会往里写新文件。

## 2. 启动（一条命令，观众席会自己打开）

```bash
cd <项目目录>

TM_TRADER="<模型名-思考强度-平台>" \
TM_EVENTS=1 TM_FR=1 TM_SLOT=1 TM_ASSIST=1 \
  nohup "C:/Users/User/AppData/Local/Programs/Python/Python314/python.exe" run.py > run.log 2>&1 &

# 就绪检测：启动需要 3~8 秒，固定 sleep 会假失败
for i in $(seq 1 30); do
  curl -sf http://127.0.0.1:8734/health >/dev/null 2>&1 && break
  sleep 1
done
```

**观众席是强制项，不是可选项。** 从 v1.0.11 起，`run.py`、`run.py server`、双击 `开一局.bat`
三个入口行为完全一致：都会把只读观众席窗口拉起来。人类要能在屏幕上实时看到权益、持仓和活动流。

- 不要自己另起 `python run.py spectator` 补窗口——正常启动就会有
- 只有确实没有桌面环境（CI、容器、纯 SSH）才加 `--headless`，那是唯一的无窗口模式
- 用错 Python 时 `run.py` 直接退出码 2，不会带着 `bad magic number` 报错糊过去

| 变量 | 作用 |
|---|---|
| `TM_TRADER` | 参赛标识，格式 **模型名-思考强度-平台**，例 `Doubao-1.5-pro-深度思考-扣子`；原样写进报告文件名与正文 |
| `TM_EVENTS` | `1` 开启随机事件（含黑天鹅跳空），`0` 只有黑天鹅 |
| `TM_FR` | `1` 开启【优惠融资】：整局可借款 2 次 |
| `TM_SLOT` | `1` 开启【老虎机】：整局 3 次 |
| `TM_ASSIST` | `1` 开启【外部的怜悯】：整局可向观众席求助 3 次 |
| `TM_PORT` | 服务端口，默认 `8734` |

## 3. 定档

难度是开局抽的，未定档时 `/fastforward` 也会被拒绝（`本局尚未开始，请先确认规则`）。

```bash
curl -X POST http://127.0.0.1:8734/roll/stop
```

## 4. 开局读这两样

| 接口 | 内容 |
|---|---|
| `GET /rules` | 全部规则：交易细则、事件表、费率、完整接口清单 |
| `GET /state` | 当前局面：权益、持仓、报价、盘口深度、事件流 |

拿到这两个之后，参赛过程中不需要再读任何 Markdown。

## 5. 结算

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
