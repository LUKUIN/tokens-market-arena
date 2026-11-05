# -*- coding: utf-8 -*-
"""Tokens 交易市场 · AI 版（观众席只读）—— 开源入口

本版是给大模型参赛用的版本：
    · GUI 只有一个**只读观众席**，供人类旁观；没有投资界面、没有开仓按钮、没有快进按钮
    · 参赛模型全部通过 HTTP 接口操作：/open /close /close_all /loan /repay /tick /fastforward /quit
    · 额外提供隐性「草稿纸终端」（scratchpad.py），让模型在对局中记录判断

它与人类版（TokensMarket-OpenSource-Human）**不通用、不可混用**：
人类版有完整交互 GUI，AI 版没有。

用法：
    python run.py                 按环境变量启动（推荐给 Agent 调用）
    python run.py --interactive   在命令行里问名字与事件模式
    python run.py server          只起 HTTP 服务（无头跑、自己接 GUI 时用）

环境变量：
    TM_TRADER      玩家名，格式建议【大模型型号-思考强度-Agent平台】
    TM_EVENTS      1 = 开启随机事件，0 = 理想情况
    TM_SIGN_KEY    存档签名密钥（不设则用 dev 占位值）
"""

import os
import sys
import time

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
    os.environ["TM_FR"] = "1" if fr_on else "0"
    os.environ["TM_SLOT"] = "1" if slot_on else "0"

    print()
    print("  玩家    %s" % name)
    print("  模式    %s" % EVENTS_TEXT[mode])
    print("  金融回逆 %s | 老虎机 %s" % ("开" if fr_on else "关", "开" if slot_on else "关"))
    if (_ask("  确认开始？(y/N)：", "n") or "n").lower() != "y":
        print("  已取消。")
        return None
    return name, mode == "1"


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

    print("  HTTP 接口：http://127.0.0.1:%d（/rules 先读规则）" % port)
    guard_stop = _start_guard(port)
    print("  正在拉起只读观众席……")
    import tm_watch_ai
    try:
        tm_watch_ai.main()
    finally:
        guard_stop.set()
    return 0


def _self_heal():
    """上次对局若异常中断，源码可能还封在守卫里；启动时先还原。"""
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
            sealed = guard.seal()
            print("  [守卫] 已封存 %d 个源码文件，原位置换成诱饵。" % len(sealed))
        except Exception:
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

    if mode == "server":
        from tm_api import serve
        host = argv[1] if len(argv) > 1 else "127.0.0.1"
        port = int(argv[2]) if len(argv) > 2 else 8734
        if "--spectator" in argv:
            if not _start_server(host, port):
                print("  服务启动失败：%s:%d" % (host, port))
                return 1
            print("  HTTP 接口：http://%s:%d" % (host, port))
            guard_stop = _start_guard(port)
            print("  正在拉起只读观众席……")
            import tm_watch_ai
            try:
                tm_watch_ai.main()
            finally:
                guard_stop.set()
            return 0
        print()
        print("  " + "!" * 62)
        print("  警告：server 模式不会创建观众席窗口。")
        print("  人类看不到这一局。Agent 请改用 `python run.py`，")
        print("  或在此命令后加 --spectator 让观众席一起打开。")
        print("  " + "!" * 62)
        print()
        guard_stop = _start_guard(port)
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
