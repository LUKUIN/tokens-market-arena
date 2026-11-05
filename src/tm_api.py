# -*- coding: utf-8 -*-
"""Tokens Trading Market — HTTP service

Endpoints:
    GET  /rules            rules
    GET  /state            account, positions, loans, prices, history
    GET  /prices           quotes
    POST /open             open a position
    POST /close            close a position
    POST /close_all        close all
    POST /tick             advance one tick
    POST /loan             take a loan {"amount": 500000} (the uplift ratio is only rolled when you borrow — that is the cost)
    POST /repay            repay {"amount": 500000} (omit amount to repay in full)
    POST /quit             end this match
    POST /reset            start a new match
    GET  /health           liveness probe
"""

import json
import os
import threading
import time
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from urllib.parse import urlparse, parse_qs

from tm_engine import Engine, TICK_SECONDS

HOME = os.path.join(os.path.dirname(os.path.abspath(__file__)), "data")
ENGINE = Engine(HOME)
SERVER = None


class Handler(BaseHTTPRequestHandler):
    server_version = "TokensMarket/2.0"

    def log_message(self, fmt, *args):
        pass

    def _send(self, obj, code=200):
        body = json.dumps(obj, ensure_ascii=False, indent=1).encode("utf-8")
        self.send_response(code)
        self.send_header("Content-Type", "application/json; charset=utf-8")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def _note(self):
        ENGINE.note_ua(self.headers.get("User-Agent", ""))

    def _body(self):
        n = int(self.headers.get("Content-Length") or 0)
        if n <= 0:
            return {}
        try:
            obj = json.loads(self.rfile.read(n).decode("utf-8"))
        except Exception:
            return {}
        return obj if isinstance(obj, dict) else {}

    def do_GET(self):
        self._note()
        path = urlparse(self.path).path.rstrip("/") or "/"
        if path == "/health":
            st = ENGINE.state()
            return self._send({"ok": True, "tick": st["tick"], "equity": st["equity"],
                               "finished": st["finished"]})
        if path == "/scratchpad":
            return self._send({"ok": True, "items": ENGINE.scratch_read()})
        if path == "/rules":
            return self._send(ENGINE.rules())
        if path == "/state":
            q = parse_qs(urlparse(self.path).query or "")
            raw = (q.get("history", ["1"])[0] or "1").strip().lower()
            with_hist = raw not in ("0", "false", "no", "off")
            return self._send(ENGINE.state(include_history=with_hist))
        if path == "/prices":
            return self._send(ENGINE.state()["prices"])
        if path == "/roll/state":
            return self._send({"ok": True, **ENGINE.roll_state()})
        if path == "/special":
            return self._send({"ok": True, **ENGINE.special_state()})
        return self._send({"ok": False, "error": "unknown endpoint: %s" % path}, 404)

    def do_POST(self):
        try:
            self._note()
            path = urlparse(self.path).path.rstrip("/") or "/"
            b = self._body()
            return self._route_post(path, b)
        except Exception as exc:
            try:
                self._send({"ok": False, "error": "Request failed: %s" % exc}, 500)
            except Exception:
                pass

    def _route_post(self, path, b):
        if path == "/open":
            return self._send(ENGINE.open_position(b.get("pair"), b.get("side"),
                                                   b.get("lots"), b.get("leverage", 1)))
        if path == "/close":
            return self._send(ENGINE.close_position(b.get("pair"), b.get("lots")))
        if path == "/close_all":
            return self._send(ENGINE.close_all())
        if path == "/tick":
            return self._send(ENGINE.manual_tick())
        if path == "/loan":
            return self._send(ENGINE.borrow(b.get("amount")))
        if path == "/repay":
            return self._send(ENGINE.repay(b.get("amount")))
        if path == "/quit":
            resp = ENGINE.quit_session()
            self._send(resp)
            # Once the player ends the game, the service and the spectator exit with it
            threading.Timer(3.0, lambda: SERVER and SERVER.shutdown()).start()
            return
        if path == "/shutdown":
            # Stop the service immediately (no settle, no data wipe); used by the spectator's "End related processes" button.
            # But an "abnormal exit" must still leave a snapshot under reports/ for later accounting.
            try:
                ENGINE.abnormal_exit_report("End processes")
            except Exception:
                pass
            self._send({"ok": True, "msg": "Service stopped (abnormal-exit report generated)"})
            threading.Timer(0.3, lambda: os._exit(0)).start()
            return
        if path == "/trader":
            return self._send(ENGINE.set_trader(b.get("name")))
        if path == "/scratchpad":
            return self._send(ENGINE.scratch_append(b.get("text")))
        if path == "/reset":
            return self._send(ENGINE.reset())
        if path == "/pause":
            return self._send(ENGINE.pause())
        if path == "/begin":
            return self._send(ENGINE.begin())
        if path == "/fastforward":
            return self._send(ENGINE.fast_forward(b.get("seconds", 300)))
        if path == "/roll/stop":
            return self._send(ENGINE.roll_stop())
        if path == "/roll/start":
            return self._send(ENGINE.start_roll())
        if path == "/special":
            return self._send(ENGINE.set_special(b.get("name"), b.get("on")))
        if path == "/slot":
            return self._send(ENGINE.slot(b.get("amount")))
        return self._send({"ok": False, "error": "unknown endpoint: %s" % path}, 404)



def _auto_tick():
    while True:
        time.sleep(TICK_SECONDS)
        try:
            st = ENGINE.tick()
            if isinstance(st, dict) and st.get("finished"):
                # Round already settled (negative time / past the limit): same as /quit, the service exits
                # -- "ended is ended": no auto restart, no idle service left spinning.
                threading.Timer(3.0, lambda: SERVER and SERVER.shutdown()).start()
                return
        except Exception:
            pass


def _roll_printer():
    """Difficulty draw countdown printer: one line per second, then two result lines once the draw is locked in.

    Only the remaining time and a "locked" marker are shown, never the current number — otherwise the AI could pick its tier.
    """
    import time as _t
    printed_stop = False
    while True:
        try:
            st = ENGINE.roll_state()
            if st.get("rolled"):
                if not printed_stop:
                    r = ENGINE._difficulty_result()
                    print("", flush=True)
                    print("  " + "=" * 46, flush=True)
                    print("   Difficulty locked: Black Swan %s | liquidity %s" % (r["gap"], r["liq"]), flush=True)
                    print("   Gap %.2f%% per tick   |   ~%.1f%% round trip on 20M notional" % (
                        r["gap_chance"] * 100,
                        14.0 * (8_000_000.0 / max(1.0, r["liquidity"]))), flush=True)
                    print("  " + "=" * 46, flush=True)
                    printed_stop = True
                _t.sleep(2.0)
                continue
            left = float(st.get("roll_left") or 0.0)
            if left > 0:
                print("  Drawing difficulty... %.1f s remaining (POST /roll/stop to lock early)" % left,
                      end=chr(13), flush=True)
        except Exception:
            pass
        _t.sleep(1.0)


def serve(host="127.0.0.1", port=8734):
    # The AI build has no GUI to trigger the draw, so it starts drawing difficulty as soon as the service is up.
    # The human build's tm_watch also calls /roll/start, but start_roll() is idempotent.
    try:
        ENGINE.start_roll()
    except Exception:
        pass

    print("")
    print("  " + "-" * 58)
    print("   Scratchpad terminal (optional): record your read and plan at any point in the match")
    print("     python scratchpad.py \"your thoughts\"   append one entry")
    print("     python scratchpad.py --list        list recorded entries")
    print("     python scratchpad.py --clear       clear it")
    print("   At settlement it is merged into the \"Scratchpad\" section of the HTML report; writing nothing does not affect settlement.")
    print("  " + "-" * 58)
    print("")
    threading.Thread(target=_auto_tick, daemon=True).start()
    threading.Thread(target=_roll_printer, daemon=True).start()
    global SERVER
    srv = ThreadingHTTPServer((host, port), Handler)
    SERVER = srv
    print("Tokens Trading Market started: http://%s:%d" % (host, port), flush=True)
    try:
        srv.serve_forever()
    except KeyboardInterrupt:
        pass
