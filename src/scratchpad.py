# -*- coding: utf-8 -*-
"""Scratchpad terminal — jot down your read and plan during a match.

Usage (no server needed; it reads and writes data/.scratchpad.jsonl directly):

    python scratchpad.py "AURA is 8% off its mean, preparing to short"
    python scratchpad.py --list        show everything recorded this match
    python scratchpad.py --count       print the entry count only
    python scratchpad.py --clear       clear this match's scratchpad
    python scratchpad.py              no arguments: continuous input mode (Ctrl+C to exit)

Every entry is flushed to disk immediately, so closing the terminal mid-match loses nothing.
The file is cleared together with the game on settlement/reset.
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
    """Read the current tick from session.json; record -1 if it cannot be read."""
    p = os.path.join(HERE, "data", "session.json")
    try:
        with io.open(p, encoding="utf-8") as f:
            return int(json.load(f).get("tick", -1))
    except Exception:
        return -1


def append(text):
    t = (text or "").strip()
    if not t:
        print("content cannot be empty")
        return False
    if len(t) > MAX_LEN:
        t = t[:MAX_LEN]
        print("(truncated to %d characters)" % MAX_LEN)
    rec = {"tick": _tick_now(), "at": round(time.time(), 3), "text": t}
    os.makedirs(os.path.dirname(PAD), exist_ok=True)
    with io.open(PAD, "a", encoding="utf-8") as f:
        f.write(json.dumps(rec, ensure_ascii=False) + chr(10))
    print("recorded (entry %d, tick %s)" % (len(_load()), rec["tick"]))
    return True


def show():
    items = _load()
    if not items:
        print("This match's scratchpad is empty.")
        return
    print("This match's scratchpad has %d entries:" % len(items))
    print("-" * 60)
    for i, x in enumerate(items, 1):
        print("[%d] tick %s" % (i, x.get("tick", "?")))
        print(x.get("text", ""))
        print("-" * 60)


def clear():
    if os.path.exists(PAD):
        os.remove(PAD)
        print("Cleared this match's scratchpad.")
    else:
        print("This match's scratchpad was already empty.")


def repl():
    print("Scratchpad terminal. Type an entry and press Enter to save; Ctrl+C to exit.")
    print("(every entry is flushed to disk immediately, so exiting mid-match loses nothing)")
    print("-" * 60)
    while True:
        try:
            line = input("> ")
        except (EOFError, KeyboardInterrupt):
            print(chr(10) + "Exited, %d entries total." % len(_load()))
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
