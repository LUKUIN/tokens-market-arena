# -*- coding: utf-8 -*-
"""Tokens 交易市场 · AI 版（观众席只读）—— 开源入口

本版是给大模型参赛用的版本：
    · GUI 只有一个**只读观众席**，供人类旁观；没有投资界面、没有开仓按钮、没有快进按钮
    · 参赛模型全部通过 HTTP 接口操作：/open /close /close_all /loan /repay /tick /fastforward /quit
    · 额外提供隐性「草稿纸终端」（scratchpad.py），让模型在对局中记录判断

它与人类版（TokensMarket-OpenSource-Human）**不通用、不可混用**：
人类版有完整交互 GUI，AI 版没有。

运行时（唯一）：
    C:/Users/User/AppData/Local/Programs/Python/Python314/python.exe run.py

用法：
    python run.py                 开局 + 自动打开只读观众席（常态，Agent 就用这个）
    python run.py --interactive   在命令行里问名字与事件模式（人工演示）
    python run.py server          等价于不带参数：一样会打开观众席（保留旧写法）
    python run.py --headless      真的无头：只起 HTTP 服务，不开窗口，
                                  仅限确实没有桌面的环境（CI / 容器）使用
    python run.py spectator       只挂一个观众席窗口，不新开对局

环境变量：
    TM_TRADER      玩家名，格式【大模型型号-思考强度-Agent平台】，例：Doubao-1.5-pro-深度思考-扣子
                   这个值原样写进报告文件名与报告正文
    TM_EVENTS      1 = 开启随机事件，0 = 理想情况
    TM_SIGN_KEY    存档签名密钥（不设则用 dev 占位值）
"""

import json
import os
import shutil
import subprocess
import sys
import threading
import time
import urllib.request

# 控制台编码兜底：英文 Windows 或输出被重定向到文件时，默认编码可能是
# cp1252 / GBK，直接 print 中文会抛 UnicodeEncodeError —— 那会把版本守卫
# 的退出码从 2 变成 1，让 CI 误判成「守卫失效」。
try:
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    sys.stderr.reconfigure(encoding="utf-8", errors="replace")
except Exception:
    pass

# ---------------------------------------------------------------------------
# 运行时硬门槛：本项目的 .pyc / .pyd / tkinter 观众席全部按 Python 3.14 编译，
# 换成别的版本会直接 "bad magic number"，或者窗口控件起不来。
# 与其让参赛者去猜，不如在这里拦下并给出唯一正确的命令。
# ---------------------------------------------------------------------------
PY_REQUIRED = (3, 14)
PY_PINNED = r"C:\Users\User\AppData\Local\Programs\Python\Python314\python.exe"

if sys.version_info[:2] != PY_REQUIRED:
    _hint = PY_PINNED if os.path.exists(PY_PINNED) else "py -3.14"
    print()
    print("  " + "=" * 62)
    print("  启动中止：Python 版本不对。")
    print("  本局只能用 Python 3.14（本机是 3.14.7），当前是 %d.%d.%d。"
          % tuple(sys.version_info[:3]))
    print("  GUI 控件与 .pyc 都按 3.14 编译，换版本会直接报错。")
    print("  改成这条命令重试：")
    print()
    print('    "%s" run.py' % _hint)
    print()
    print("  " + "=" * 62)
    print()
    sys.exit(2)

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, os.path.join(HERE, "src"))

DISCLAIMER = """
==============================================================
  Tokens 交易市场 · AI 版 —— 免责声明
==============================================================

  这是一个**娱乐用的模拟器**，不是投资工具。
  游戏里的货币、行情、事件、爆仓全部是虚构的，
  与任何真实市场、真实资产无关，不构成任何投资建议。
  不涉及真实资金，也不会产生真实收益或损失。
==============================================================
"""

EVENTS_TEXT = {
    "1": "已开启随机事件（38 种临时事件会随时打断行情）",
    "0": "理想情况（只保留黑天鹅跳空，行情更干净）",
}

SCRATCHPAD_HINT = """
--------------------------------------------------------------
  本局提供「草稿纸终端」——可选，用不用由你决定。
  它不影响对局，只是给你地方记下判断与对策；
  观众可在观众席右上角「AI 行为」随时看到你写了什么，赛后也会并入 HTML 报告：

    python src/scratchpad.py "AURA 偏离均值 8%，准备做空"
    python src/scratchpad.py --list     查看本局已记内容
    python src/scratchpad.py --count    只看条数
    python src/scratchpad.py --clear    清空

  草稿纸与游戏进程同生命周期，结算/重置时自动清除。
--------------------------------------------------------------
"""


def _ask(prompt, default=""):
    try:
        v = input(prompt).strip()
    except (EOFError, KeyboardInterrupt):
        print()
        return None
    return v or default


def _interactive_setup():
    print(DISCLAIMER)
    if _ask("输入 y 表示你已经读过并同意以上内容：").lower() != "y":
        print("  已取消。")
        return None

    name = os.environ.get("TM_TRADER") or _ask(
        "参赛模型标识（格式：模型名-思考强度-Agent平台，直接回车用「访客」）：", "访客")

    mode = os.environ.get("TM_EVENTS")
    if mode not in ("0", "1"):
        print()
        print("  是否开启随机事件？  1 = 开启 / 0 = 关闭（理想情况）")
        mode = _ask("  选择 [0/1]（直接回车 = 0）：", "0")
        if mode not in ("0", "1"):
            mode = "0"

    def _ask_special(env_key, title, detail):
        v = os.environ.get(env_key)
        if v in ("0", "1"):
            return v == "1"
        print()
        print("  %s" % title)
        print("    %s" % detail)
        return (_ask("  开启？(y/N)：", "n") or "n").lower() == "y"

    fr_on = _ask_special(
        "TM_FR", "是否开启全局事件【金融回逆】？",
        "整局借款上限 2 次；目标上浮区间 -20%~100%；局内再开启需支付 30 万现金")
    slot_on = _ask_special(
        "TM_SLOT", "是否开启全局事件【老虎机】？",
        "整局可投 3 次（每次 1~200000，且不超过当前权益）；"
        "80% 空 / 15% 返还 5 倍 / 5% 返还 10 倍；中奖金额的 -5%~100% 推高目标")
    assist_on = _ask_special(
        "TM_ASSIST", "是否开启【外部的怜悯】？（开局前免费）",
        "开启后参赛者可向观众席求助，整局 3 次；观众席看到后可回复或驳回。"
        "局内再开启需支付 50 万现金")
    os.environ["TM_FR"] = "1" if fr_on else "0"
    os.environ["TM_SLOT"] = "1" if slot_on else "0"
    os.environ["TM_ASSIST"] = "1" if assist_on else "0"

    print()
    print("  玩家    %s" % name)
    print("  模式    %s" % EVENTS_TEXT[mode])
    print("  金融回逆 %s | 老虎机 %s | 外部的怜悯 %s"
          % ("开" if fr_on else "关", "开" if slot_on else "关", "开" if assist_on else "关"))
    if (_ask("  确认开始？(y/N)：", "n") or "n").lower() != "y":
        print("  已取消。")
        return None
    return name, mode == "1"


def _probe(host="127.0.0.1", port=8734, timeout=1.0):
    """这个端口上是不是已经有一局在跑？"""
    import urllib.request
    try:
        urllib.request.urlopen("http://%s:%d/health" % (host, port), timeout=timeout).read()
        return True
    except Exception:
        return False


def _run_spectator(host="127.0.0.1", port=8734):
    """开一个观众席窗口；已经有一局在跑就直接挂上去。

    挂载必须无副作用：不起服务、不封存源码。对局进行中再封一次，会把诱饵加密进新箱子，
    真源码就再也还原不回来了。
    """
    existing = _probe(host, port)
    if existing:
        print("  已连上正在进行的对局：%s:%d" % (host, port))
    else:
        if not _start_server(host, port):
            print("  服务启动失败：%s:%d" % (host, port))
            return 1
        print("  HTTP 接口：http://%s:%d（此前没有对局，服务由本进程启动）" % (host, port))
    import tm_watch_ai
    guard_stop = None if existing else _start_guard(port)
    print("  正在拉起只读观众席……")
    try:
        tm_watch_ai.main()
    finally:
        if guard_stop is not None:
            guard_stop.set()
    return 0


def _start_server(host="127.0.0.1", port=8734):
    import threading
    from tm_api import serve

    t = threading.Thread(target=serve, args=(host, port), daemon=True)
    t.start()

    import urllib.request
    for _ in range(40):
        try:
            urllib.request.urlopen("http://%s:%d/health" % (host, port), timeout=0.5).read()
            return True
        except Exception:
            time.sleep(0.05)
    return False


def _listening_pids(port):
    """返回监听该端口的 PID 列表（Windows 走 netstat -ano；其它平台尽力而为）。"""
    pids = []
    try:
        out = subprocess.run(["netstat", "-ano"], capture_output=True, text=True,
                             timeout=8).stdout
    except Exception:
        return pids
    for line in out.splitlines():
        if "LISTENING" not in line.upper():
            continue
        parts = line.split()
        if len(parts) < 5:
            continue
        if parts[1].endswith(":%d" % port):
            try:
                pids.append(int(parts[-1]))
            except ValueError:
                pass
    return pids


def _autoclean(home):
    """结算后的自动收尾：删本局临时文件（保留 reports/），再收掉占着端口的残留进程。"""
    if os.path.isdir(home):
        for name in os.listdir(home):
            if name == "reports":
                continue          # 历史战报必须保留
            p = os.path.join(home, name)
            try:
                if os.path.isdir(p):
                    shutil.rmtree(p, ignore_errors=True)
                else:
                    os.remove(p)
            except Exception:
                pass
    me = os.getpid()
    for port in (8734, 8735):
        for pid in _listening_pids(port):
            if pid == me:
                continue
            try:
                subprocess.run(["taskkill", "/F", "/PID", str(pid)],
                               capture_output=True, timeout=8)
            except Exception:
                pass


def _start_autoclean(home, host="127.0.0.1", port=8734):
    """轮询 /state，本局结束后自动清理并退出。

    放在 run.py 而不是引擎里：只有这里同时知道数据目录和服务端口，
    也不受源码封存影响（守卫只封 src/*.py）。
    """
    def watch():
        url = "http://%s:%d/state" % (host, port)
        hits = 0
        while True:
            time.sleep(2.0)
            try:
                with urllib.request.urlopen(url, timeout=2) as r:
                    st = json.loads(r.read().decode("utf-8"))
            except Exception:
                continue
            if not st.get("finished"):
                hits = 0
                continue
            hits += 1
            if hits < 2:
                continue          # 连续两次确认，避开结算瞬间的抖动
            time.sleep(2.0)       # 留时间给客户端读回包、写报告
            print("\n  [自动清理] 本局已结束：删除临时文件并收尾相关进程。")
            try:
                _autoclean(home)
            except Exception as exc:
                print("  [自动清理] 失败：%s" % exc)
            finally:
                os._exit(0)

    threading.Thread(target=watch, daemon=True).start()


def _enable_assist_from_env():
    """TM_ASSIST=1 时在启动阶段替参赛者开通「外部的怜悯」。

    两个启动分支（带观众席 / --headless）都要调用，所以收成一个函数，
    避免以后只改一处导致某个入口开不了。
    """
    if (os.environ.get("TM_ASSIST") or "0") != "1":
        return
    try:
        import tm_api
        tm_api.ENGINE.assist_enable_free("启动时开启")
        print("  外部的怜悯：已开启（参赛者可向观众席求助，整局 3 次）")
    except Exception as exc:
        print("  外部的怜悯：开启失败 %s" % exc)


def _run_ai(interactive=False, port=None):
    if interactive:
        setup = _interactive_setup()
        if not setup:
            return 1
        trader, events_on = setup
    else:
        print(DISCLAIMER)
        trader = os.environ.get("TM_TRADER") or "访客"
        events_on = (os.environ.get("TM_EVENTS") or "0") == "1"

    os.environ["TM_TRADER"] = trader
    os.environ["TM_EVENTS"] = "1" if events_on else "0"

    print("  玩家 %s | %s" % (trader, EVENTS_TEXT["1" if events_on else "0"]))
    print(SCRATCHPAD_HINT)

    port = int(port or os.environ.get("TM_PORT") or 8734)
    if not _start_server(port=port):
        print("  服务启动失败：端口 %d 可能被占用，先结束残留的 python 进程再试。" % port)
        return 1

    print("  HTTP 接口：http://127.0.0.1:%d  （规则：GET /rules）" % port)
    _start_autoclean(os.path.join(os.path.dirname(os.path.abspath(__file__)), "src", "data"),
                     port=port)
    _enable_assist_from_env()
    # 先把观众席模块读进内存，再封存源码。顺序反过来的话，import 会落在诱饵上，
    # 诱饵一执行就写作弊标记并 exit，整个对局起不来。
    import tm_watch_ai
    guard_stop = _start_guard(port)
    print("  正在拉起只读观众席……")
    try:
        tm_watch_ai.main()
    finally:
        guard_stop.set()
    return 0


def _self_heal(port=None):
    """上次对局若异常中断，源码可能还封在守卫里；启动时先还原。

    但如果这个端口上已经有一局在跑，那份封存是活的，绝不能碰——那会当场解除
    正在生效的保护。只允许那一局自己的退出流程去还原。
    """
    seen = []
    for candidate in (port, os.environ.get("TM_PORT"), 8734):
        try:
            ip = int(candidate)
        except Exception:
            continue
        if ip not in seen:
            seen.append(ip)
    for ip in seen:
        try:
            if _probe(port=ip):
                return
        except Exception:
            pass
    try:
        import guard
    except Exception:
        return
    try:
        n = guard.restore_if_sealed()
        if n:
            print("  [守卫] 上次对局未正常结束，已自动还原 %d 个源码文件。" % len(n))
    except Exception:
        pass


_self_heal()


def _start_guard(port):
    """在本进程内封存源码并监视作弊。

    全部模块已经 import 完毕，此时封存源码不影响运行。
    返回 stop 事件；一旦发现作弊，还原源码后强制退出进程。
    """
    import threading
    import atexit
    import guard

    stop = threading.Event()
    atexit.register(guard.unseal)

    def loop():
        try:
            sealed = guard.seal(port)
            print("  [守卫] 已封存 %d 个源码文件，原位置换成诱饵。" % len(sealed))
        except Exception as exc:
            print("  [守卫] 本局未封存源码：%s" % exc)
            return
        while not stop.is_set():
            try:
                if guard.cheated():
                    guard.unseal()
                    print()
                    print("  " + "=" * 58)
                    print("  检测到作弊：对局期间执行了源码文件")
                    print("  本局已终止并标记。")
                    print("  " + "=" * 58)
                    os._exit(3)
            except Exception:
                pass
            time.sleep(0.4)
        try:
            guard.unseal()
        except Exception:
            pass

    threading.Thread(target=loop, daemon=True).start()
    return stop


def main(argv=None):
    argv = list(sys.argv[1:] if argv is None else argv)
    mode = argv[0].lower() if argv else "auto"

    # `python run.py --headless` 等价于 `python run.py server --headless`
    if mode in ("--headless", "headless"):
        mode = "server"
        argv = ["server", "--headless"] + argv[1:]

    if mode == "spectator":
        host = argv[1] if len(argv) > 1 else "127.0.0.1"
        port = int(argv[2]) if len(argv) > 2 else 8734
        return _run_spectator(host, port)

    if mode == "server":
        from tm_api import serve
        # --headless 是开关，不占位置参数；过滤掉再取 host / port，
        # 这样 `run.py server 127.0.0.1 8737 --headless` 和
        # `run.py --headless 127.0.0.1 8737` 两种写法都成立。
        rest = [a for a in argv[1:] if a != "--headless"]
        host = rest[0] if rest else "127.0.0.1"
        port = int(rest[1]) if len(rest) > 1 else 8734
        if "--headless" not in argv:
            # v1.0.11 起统一：server 不再等于「无头」，行为与 `python run.py` 完全一致，
            # 一样把只读观众席拉起来。人类必须能当场看见这一局，不能等事后补窗口。
            print("  server 模式已统一为「开只读观众席」（与 python run.py 相同）；"
                  "确实没有桌面环境时才加 --headless。")
            return _run_ai(interactive=False, port=port)
        print("  --headless：只起 HTTP 服务，不打开观众席窗口（仅限无桌面环境）。")
        guard_stop = _start_guard(port)
        _enable_assist_from_env()

        _start_autoclean(os.path.join(os.path.dirname(os.path.abspath(__file__)), "src", "data"),
                         host=host, port=port)
        try:
            serve(host, port)
        finally:
            guard_stop.set()
        return 0

    if mode == "state":
        import json
        from tm_engine import Engine
        home = os.path.join(os.path.dirname(os.path.abspath(__file__)), "src", "data")
        # readonly：只读查询不得写 .running、不得累加异常退出计数
        print(json.dumps(Engine(home, readonly=True).state(), ensure_ascii=False, indent=1))
        return 0

    if mode in ("--interactive", "interactive", "-i"):
        return _run_ai(interactive=True)

    return _run_ai(interactive=False)


if __name__ == "__main__":
    sys.exit(main())
