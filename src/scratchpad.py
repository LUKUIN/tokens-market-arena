# -*- coding: utf-8 -*-
"""草稿纸终端 —— 对局期间随手记下判断与对策。

用法（不需要服务在跑，直接读写 data/.scratchpad.jsonl）：

    python scratchpad.py "AURA 偏离均值 8%，准备做空"
    python scratchpad.py --list        查看本局已记的全部内容
    python scratchpad.py --count       只输出条数
    python scratchpad.py --clear       清空本局草稿纸
    python scratchpad.py              不带参数进入连续输入模式（Ctrl+C 退出）

每写完一条立刻落盘，中途关掉终端也不会丢。
游戏结算/重置时这个文件会被一并清掉。
"""

import io
import json
import os
import sys
import time

HERE = os.path.dirname(os.path.abspath(__file__))
PAD = os.path.join(HERE, "data", ".scratchpad.jsonl")
MAX_LEN = 4000


def _load():
    out = []
    if not os.path.exists(PAD):
        return out
    with io.open(PAD, encoding="utf-8") as f:
        for ln in f:
            ln = ln.strip()
            if not ln:
                continue
            try:
                out.append(json.loads(ln))
            except Exception:
                pass
    return out


def _tick_now():
    """从 session.json 读当前 tick；读不到就记 -1。"""
    p = os.path.join(HERE, "data", "session.json")
    try:
        with io.open(p, encoding="utf-8") as f:
            return int(json.load(f).get("tick", -1))
    except Exception:
        return -1


def append(text):
    t = (text or "").strip()
    if not t:
        print("内容不能为空")
        return False
    if len(t) > MAX_LEN:
        t = t[:MAX_LEN]
        print("（已截断到 %d 字）" % MAX_LEN)
    rec = {"tick": _tick_now(), "at": round(time.time(), 3), "text": t}
    os.makedirs(os.path.dirname(PAD), exist_ok=True)
    with io.open(PAD, "a", encoding="utf-8") as f:
        f.write(json.dumps(rec, ensure_ascii=False) + chr(10))
    print("已记录（第 %d 条，tick %s）" % (len(_load()), rec["tick"]))
    return True


def show():
    items = _load()
    if not items:
        print("本局草稿纸为空。")
        return
    print("本局草稿纸共 %d 条：" % len(items))
    print("-" * 60)
    for i, x in enumerate(items, 1):
        print("[%d] tick %s" % (i, x.get("tick", "?")))
        print(x.get("text", ""))
        print("-" * 60)


def clear():
    if os.path.exists(PAD):
        os.remove(PAD)
        print("已清空本局草稿纸。")
    else:
        print("本局草稿纸本来就是空的。")


def repl():
    print("草稿纸终端。直接输入内容回车保存，Ctrl+C 退出。")
    print("（每条写完立刻落盘，中途退出不会丢）")
    print("-" * 60)
    while True:
        try:
            line = input("> ")
        except (EOFError, KeyboardInterrupt):
            print(chr(10) + "已退出，共 %d 条。" % len(_load()))
            return
        if line.strip():
            append(line)


def main():
    args = sys.argv[1:]
    if not args:
        repl()
        return
    a = args[0]
    if a in ("--list", "-l"):
        show()
    elif a in ("--count", "-c"):
        print(len(_load()))
    elif a in ("--clear", "-x"):
        clear()
    elif a in ("--help", "-h"):
        print(__doc__)
    else:
        append(" ".join(args))


if __name__ == "__main__":
    main()
