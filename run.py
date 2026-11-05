# -*- coding: utf-8 -*-
"""Tokens 交易市场 · 人类版（GUI 交互）—— 开源入口

本版是给人类玩家亲手玩的版本，包含完整交互界面：
    投资界面（开仓 / 平仓 / 借贷 / 快进）、规则窗、难度盲盒、免责声明。

它与 AI 版（TokensMarket-OpenSource-AI）**不通用、不可混用**：
AI 版只有只读观众席，没有投资界面，所有操作走 HTTP 接口。

用法：
    python run.py              交互式开局
    python run.py server       只起 HTTP 服务（调试用）
    python run.py state        命令行看当前局面

环境变量：
    TM_TRADER      玩家名，设了就不再问
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
  Tokens 交易市场 · 人类版 —— 免责声明
==============================================================

  这是一个**娱乐用的模拟器**，不是投资工具。

  · 游戏里的货币、行情、事件、爆仓全部是虚构的
  · 与任何真实市场、真实资产无关
  · 不构成任何投资建议或交易策略
  · 不涉及真实资金，也不会产生真实收益或损失

  如果你在现实里做高杠杆交易，风险远高于这里的任何数字。

==============================================================
"""

EVENTS_TEXT = {
    "1": "已开启随机事件（35 种临时事件会随时打断行情）",
    "0": "理想情况（只保留黑天鹅跳空，行情更干净）",
}


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

    name = os.environ.get("TM_TRADER") or _ask("你的名字（直接回车用「访客」）：", "访客")

    mode = os.environ.get("TM_EVENTS")
    if mode not in ("0", "1"):
        print()
        print("  是否开启随机事件？")
        print("    1 = 开启（难度更高，行情随时被事件打断）")
        print("    0 = 关闭（理想情况，只有黑天鹅跳空）")
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
        "整局可投 3 次（每次 1~100000，且不超过当前权益）；"
        "70% 空 / 25% 10 倍 / 5% 20 倍；中奖金额的 1%~50% 推高目标")
    os.environ["TM_FR"] = "1" if fr_on else "0"
    os.environ["TM_SLOT"] = "1" if slot_on else "0"

    print()
    print("  即将开始：")
    print("    玩家    %s" % name)
    print("    模式    %s" % EVENTS_TEXT[mode])
    print("    金融回逆 %s" % ("已开启" if fr_on else "未开启"))
    print("    老虎机   %s" % ("已开启" if slot_on else "未开启"))
    print()
    if (_ask("  确认开始？(y/N)：", "n") or "n").lower() != "y":
        print("  已取消。")
        return None
    return name, mode == "1"


def _start_server(host="127.0.0.1", port=8734):
    """在后台线程里起 HTTP 服务，主线程留给 GUI。"""
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


def _run_human():
    setup = _interactive_setup()
    if not setup:
        return 1
    trader, events_on = setup
    os.environ["TM_TRADER"] = trader
    os.environ["TM_EVENTS"] = "1" if events_on else "0"

    if not _start_server():
        print("  服务启动失败：端口 8734 可能被占用，先结束残留的 python 进程再试。")
        return 1

    # 交互界面：内部会先选分辨率，再走「难度盲盒 → 规则窗 → 主 GUI」
    import tm_watch
    tm_watch.main()
    return 0


def main(argv=None):
    argv = list(sys.argv[1:] if argv is None else argv)
    mode = argv[0].lower() if argv else "human"

    if mode == "server":
        from tm_api import serve
        host = argv[1] if len(argv) > 1 else "127.0.0.1"
        port = int(argv[2]) if len(argv) > 2 else 8734
        serve(host, port)
        return 0

    if mode == "state":
        import json
        from tm_api import ENGINE
        print(json.dumps(ENGINE.state(), ensure_ascii=False, indent=1))
        return 0

    return _run_human()


if __name__ == "__main__":
    sys.exit(main())
