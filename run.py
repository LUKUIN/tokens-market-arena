# -*- coding: utf-8 -*-
"""Tokens Trading Market · AI Edition (read-only spectator) — open-source entry point

This build is the version for large-model contestants:
    · The GUI has only a **read-only spectator stand** for humans to watch; no investment panel, no open-position button, no fast-forward button
    · Every contestant operates through the HTTP API: /open /close /close_all /loan /repay /fastforward /quit
    · It additionally provides a hidden "scratchpad terminal" (POST /scratchpad) where a model can record its reasoning during a match

It is **not compatible with, and cannot be mixed with**, the human edition (TokensMarket-OpenSource-Human):
the human edition has a full interactive GUI; the AI edition does not.

Runtime (the only supported one):
    C:/Users/User/AppData/Local/Programs/Python/Python314/python.exe run.py

Usage:
    python run.py                 start the match AND open the read-only spectator (the normal path)
    python run.py --interactive   prompt for the name and event mode on the command line (human demo)
    python run.py server          same as no argument: it opens the spectator too (kept for old scripts)
    python run.py --headless      true headless: HTTP service without a window,
                                  for environments with no desktop (CI / containers)
    python run.py spectator       attach a spectator window only; does not start a new match

Environment variables:
    TM_TRADER      player name, format [model name-reasoning effort-agent platform]
                   e.g. Doubao-1.5-pro-thinking-coze; written verbatim into the report filename
                   and the report body
    TM_EVENTS      1 = enable random events, 0 = ideal conditions
    TM_SIGN_KEY    save-file signing key (a dev placeholder is used if unset)
"""

import os
import sys
import time

# Console encoding fallback: an English Windows console or redirected output
# defaults to cp1252/GBK, and printing non-ASCII text raises
# UnicodeEncodeError, which turns the guard's exit code 2 into 1 and makes
# CI report a false "guard failure".
try:
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    sys.stderr.reconfigure(encoding="utf-8", errors="replace")
except Exception:
    pass

# ---------------------------------------------------------------------------
# Hard runtime gate. The .pyc / .pyd files and the tkinter spectator are all
# built against Python 3.14; any other interpreter gives "bad magic number" or
# fails to create the window. Fail early with the one correct command instead
# of letting the contestant guess.
# ---------------------------------------------------------------------------
PY_REQUIRED = (3, 14)
PY_PINNED = r"C:\Users\User\AppData\Local\Programs\Python\Python314\python.exe"

if sys.version_info[:2] != PY_REQUIRED:
    _hint = PY_PINNED if os.path.exists(PY_PINNED) else "py -3.14"
    print()
    print("  " + "=" * 62)
    print("  Startup aborted: wrong Python version.")
    print("  This match runs on Python 3.14 only (3.14.7 on this machine); current is %d.%d.%d."
          % tuple(sys.version_info[:3]))
    print("  The GUI widgets and .pyc files are built for 3.14; another version will fail.")
    print("  Re-run with:")
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
  Tokens Trading Market · AI Edition — Disclaimer
==============================================================

  This is a **simulator for entertainment**, not an investment tool.
  The currency, prices, events and liquidations in the game are entirely fictional,
  unrelated to any real market or real asset, and constitute no investment advice.
  No real funds are involved, and no real profit or loss will be produced.
==============================================================
"""

EVENTS_TEXT = {
    "1": "Random events enabled (38 temporary events can interrupt the market at any moment)",
    "0": "Ideal conditions (only Black Swan gaps kept; cleaner price action)",
}

SCRATCHPAD_HINT = """
--------------------------------------------------------------
  This match provides a "scratchpad terminal" — optional; whether you use it is up to you.
  It does not affect the match; it only gives you somewhere to write down your read and your plan;
  spectators can see what you wrote at any time through "AI Notes" in the top-right of the spectator stand, and it is merged into the HTML report after the match:

    POST /scratchpad   {"text": "AURA is 8% off its mean, preparing to short"}
    GET  /scratchpad?count=1                                    show the entry count only
    GET  /scratchpad                                            show everything recorded
    POST /scratchpad   {"clear": true}                          clear it

  Note: during a match src/*.py has been sealed into non-executable decoys,
  so use the HTTP endpoints above and never run any .py file from the repo.

  The scratchpad shares the game process lifetime and is cleared automatically on settlement/reset.
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
    if _ask("Type y to confirm that you have read and agree to the above:").lower() != "y":
        print("  Cancelled.")
        return None

    name = os.environ.get("TM_TRADER") or _ask(
        "Contestant ID (format: model name-reasoning effort-agent platform; press Enter to use \"guest\"):", "Guest")

    mode = os.environ.get("TM_EVENTS")
    if mode not in ("0", "1"):
        print()
        print("  Enable random events?  1 = on / 0 = off (ideal conditions)")
        mode = _ask("  Choose [0/1] (press Enter = 1):", "1")
        if mode not in ("0", "1"):
            mode = "1"

    def _ask_special(env_key, title, detail):
        v = os.environ.get(env_key)
        if v in ("0", "1"):
            return v == "1"
        print()
        print("  %s" % title)
        print("    %s" % detail)
        return (_ask("  Enable? (y/N):", "n") or "n").lower() == "y"

    fr_on = _ask_special(
        "TM_FR", "Enable the global event [Preferred Financing]?",
        "No cap on the number of loans (still bounded by the 3,000,000 pool); "
        "target uplift +0.01%% to +100%% (always raises it); start of match only")
    slot_on = _ask_special(
        "TM_SLOT", "Enable the global event [Slot Machine]?",
        "3 plays per match (1~200000 each, never above current equity); 80% nothing / 15% refund 5x / 5% refund 10x; winnings lift the target by -5%~100%")
    assist_on = _ask_special(
        "TM_ASSIST", "Enable Outside Mercy? (free before the match starts)",
        "Lets the contestant ask the spectators for help, 3 times per match; spectators may reply "
        "or decline. Enabling it after the start costs 500,000 cash")
    os.environ["TM_EVENTS"] = mode
    os.environ["TM_FR"] = "1" if fr_on else "0"
    os.environ["TM_SLOT"] = "1" if slot_on else "0"
    os.environ["TM_ASSIST"] = "1" if assist_on else "0"

    print()
    print("  Player  %s" % name)
    print("  Mode    %s" % EVENTS_TEXT[mode])
    print("  Preferred Financing %s | Slot Machine %s" % ("on" if fr_on else "off", "on" if slot_on else "off"))
    if (_ask("  Start now? (y/N):", "n") or "n").lower() != "y":
        print("  Cancelled.")
        return None
    return name, mode == "1"


def _probe(host="127.0.0.1", port=8734, timeout=1.0):
    """Is a match already answering on this port?"""
    import urllib.request
    try:
        urllib.request.urlopen("http://%s:%d/health" % (host, port), timeout=timeout).read()
        return True
    except Exception:
        return False


def _run_spectator(host="127.0.0.1", port=8734):
    """Open a spectator window, attaching to a running match when there is one.

    Attaching must have no side effects: no server, no guard, no sealing. Sealing on
    attach would re-encrypt decoys over a live vault and destroy the real sources.
    """
    existing = _probe(host, port)
    if existing:
        print("  Attaching to the match already running on %s:%d." % (host, port))
    else:
        if not _start_server(host, port):
            print("  Failed to start the service on %s:%d." % (host, port))
            return 1
        print("  HTTP API: http://%s:%d (no match was running; the server was started here)" % (host, port))
    import tm_watch_ai
    guard_stop = None if existing else _start_guard(port)
    print("  Launching the read-only spectator stand...")
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
            return t
        except Exception:
            time.sleep(0.05)
    return None


def _enable_assist_from_env():
    """Enable Outside Mercy at startup when TM_ASSIST=1.

    Both launch branches (with spectator / --headless) call this, so it lives in
    one place: editing only one copy would leave one entry point unable to enable it.
    """
    if (os.environ.get("TM_ASSIST") or "0") != "1":
        return
    try:
        import tm_api
        tm_api.ENGINE.assist_enable_free("enabled at startup")
        print("  Outside Mercy: enabled (the contestant may ask the spectators 3 times)")
    except Exception as exc:
        print("  Outside Mercy: failed to enable (%s)" % exc)


def _run_ai(interactive=False, port=None):
    if interactive:
        setup = _interactive_setup()
        if not setup:
            return 1
        trader, events_on = setup
    else:
        print(DISCLAIMER)
        trader = os.environ.get("TM_TRADER") or "Guest"
        # Match Start Match.bat and the engine's _env_events() default: events on when unset
        events_on = (os.environ.get("TM_EVENTS") or "1") == "1"

    os.environ["TM_TRADER"] = trader
    os.environ["TM_EVENTS"] = "1" if events_on else "0"

    print("  Player %s | %s" % (trader, EVENTS_TEXT["1" if events_on else "0"]))
    print(SCRATCHPAD_HINT)

    port = int(port or os.environ.get("TM_PORT") or 8734)
    server_thread = _start_server(port=port)
    if not server_thread:
        print("  Failed to start the service: port %d may be in use; kill any leftover python processes and try again." % port)
        return 1

    print("  HTTP API: http://127.0.0.1:%d  (rules: GET /rules)" % port)
    _enable_assist_from_env()
    # The spectator runs in its own subprocess. It is a display layer, not the host of
    # the match: closing it, crashing it, or failing to open it (another instance holds
    # port 8735) must never touch the service. Two preconditions before changing this:
    #   1. tm_watch_ai.py is not sealed (the guard seals engine / api / scratchpad only)
    #   2. that module imports nothing but the standard library, so it starts on its own
    base = os.path.dirname(os.path.abspath(__file__))
    spectator = None
    try:
        spectator = subprocess.Popen(
            [sys.executable, "-c",
             "import sys, os; sys.path.insert(0, os.path.join(os.getcwd(), 'src')); "
             "import tm_watch_ai; tm_watch_ai.main()"],
            cwd=base)
        print("  Launching the read-only spectator stand (pid %d)..." % spectator.pid)
    except Exception as exc:
        print("  Spectator failed to start: %s (the match service keeps running)" % exc)

    guard_stop = _start_guard(port)
    try:
        server_thread.join()      # returns once /quit or /shutdown stops the service
    except KeyboardInterrupt:
        print("  Interrupted, shutting down...")
    finally:
        guard_stop.set()
        if spectator is not None:
            try:
                spectator.terminate()
            except Exception:
                pass
        # The service has exited: clean this match's temp files if it settled.
        # _start_autoclean alone is not enough — it waits for two confirmations plus
        # two more seconds, while /quit shuts the service down after three, so the
        # main process usually leaves first and strands session.json.
        try:
            import tm_api
            if (tm_api.ENGINE.state() or {}).get("finished"):
                _autoclean(os.path.join(base, "src", "data"))
        except Exception as exc:
            print("  Failed to clean up: %s" % exc)
    return 0


def _start_guard(port):
    """Seal the sources and watch for cheating, in this process.

    Starts a daemon thread: sealing the sources is safe here because every module
    is already imported. Returns a stop event; on a cheat the process exits hard
    after restoring the sources.
    """
    import threading
    import atexit
    import guard

    stop = threading.Event()
    atexit.register(guard.unseal)

    def loop():
        try:
            sealed = guard.seal(port)
            print("  [GUARD] sealed %d source file(s); decoys are in place." % len(sealed))
        except Exception as exc:
            print("  [GUARD] sources not sealed for this match: %s" % exc)
            return
        while not stop.is_set():
            try:
                if guard.cheated():
                    guard.unseal()
                    print()
                    print("  " + "=" * 58)
                    print("  CHEATING DETECTED: a source file was executed during a live match")
                    print("  The match is terminated and flagged.")
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


def _self_heal(port=None):
    """A crashed match may have left the sources sealed. Restore them before importing.

    But if something already answers on this port, its seal is LIVE: touching it would
    lift the protection of a running match. Only that match's own exit path may restore
    its sources, which is why this check comes first.
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
            print("  [GUARD] previous match did not shut down cleanly; restored %d source file(s)." % len(n))
    except Exception:
        pass


_self_heal()


def main(argv=None):
    argv = list(sys.argv[1:] if argv is None else argv)
    mode = argv[0].lower() if argv else "auto"

    # `python run.py --headless` is the same as `python run.py server --headless`
    if mode in ("--headless", "headless"):
        mode = "server"
        argv = ["server", "--headless"] + argv[1:]

    if mode == "spectator":
        host = argv[1] if len(argv) > 1 else "127.0.0.1"
        port = int(argv[2]) if len(argv) > 2 else 8734
        return _run_spectator(host, port)

    if mode == "server":
        from tm_api import serve
        # --headless is a switch, not a positional argument. Filter it out before reading
        # host / port so both `run.py server 127.0.0.1 8737 --headless` and
        # `run.py --headless 127.0.0.1 8737` work.
        rest = [a for a in argv[1:] if a != "--headless"]
        host = rest[0] if rest else "127.0.0.1"
        port = int(rest[1]) if len(rest) > 1 else 8734
        if "--headless" not in argv:
            # Since v1.0.11 `server` no longer means "headless": it behaves exactly like
            # `python run.py` and opens the read-only spectator. A human must be able to
            # watch the match live, not attach a window afterwards.
            print("  server mode now opens the read-only spectator too "
                  "(same as `python run.py`); add --headless only when there is no desktop.")
            return _run_ai(interactive=False, port=port)
        print("  --headless: HTTP service only, no spectator window (no-desktop environments only).")
        guard_stop = _start_guard(port)
        _enable_assist_from_env()

        try:
            serve(host, port)
        finally:
            guard_stop.set()
        return 0

    if mode == "state":
        import json
        from tm_engine import Engine
        home = os.path.join(os.path.dirname(os.path.abspath(__file__)), "src", "data")
        # readonly: read-only queries must not write .running or bump the abnormal-exit counter
        print(json.dumps(Engine(home, readonly=True).state(), ensure_ascii=False, indent=1))
        return 0

    if mode in ("--interactive", "interactive", "-i"):
        return _run_ai(interactive=True)

    return _run_ai(interactive=False)


if __name__ == "__main__":
    sys.exit(main())
