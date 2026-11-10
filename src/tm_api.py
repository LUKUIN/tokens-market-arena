# -*- coding: utf-8 -*-
"""Tokens Trading Market — HTTP service

Endpoints:
    GET  /rules            rules
    GET  /state            account, positions, loans, prices, history
    GET  /prices           quotes
    POST /open             open a position
    POST /close            close a position
    POST /close_all        close all
    POST /loan             take a loan {"amount": 500000} (the uplift ratio is only rolled when you borrow — that is the cost)
    POST /repay            repay {"amount": 500000} (omit amount to repay in full)
    POST /quit             end this match (refused above the target with positions; close_all first)
    POST /reset            start a new match
    GET  /health           liveness probe
"""

import json
import os
import shutil
import threading
import time
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from urllib.parse import urlparse, parse_qs

from tm_engine import Engine, TICK_SECONDS, ENGINE_VERSION, PROTOCOL_VERSION, TAIL_SPEED

HOME = os.path.join(os.path.dirname(os.path.abspath(__file__)), "data")
ENGINE = Engine(HOME)
SERVER = None


def _purge_home(home):
    """Delete this match's runtime files after settlement (keep reports/)."""
    if not os.path.isdir(home):
        return
    for name in os.listdir(home):
        if name == "reports":
            continue
        p = os.path.join(home, name)
        try:
            if os.path.isdir(p):
                shutil.rmtree(p, ignore_errors=True)
            else:
                os.remove(p)
        except Exception:
            pass


def _hard_exit():
    """Restore sealed sources, then call os._exit.

    os._exit skips atexit and finally; without this unseal the next start imports a
    decoy, which immediately calls sys.exit(1) and prints "CHEATING DETECTED" --
    it looks like a false cheating verdict.
    """
    try:
        import sys
        root = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
        if root not in sys.path:
            sys.path.insert(0, root)
        import guard
        guard.unseal()
    except Exception:
        pass
    try:
        _purge_home(HOME)
    except Exception:
        pass
    os._exit(0)



MAX_BODY_BYTES = 1 << 20


class _BodyTooLarge(Exception):
    """Request body over the cap: maps to HTTP 413 instead of 500."""


class Handler(BaseHTTPRequestHandler):
    server_version = "TokensMarket/2.0"

    def log_message(self, fmt, *args):
        pass

    def _send(self, obj, code=200):
        # No pretty-printing: /state is fetched every 300 ms and indent=1 inflates the
        # payload by 30%+; the consumer is a program, not a human reading JSON.
        body = json.dumps(obj, ensure_ascii=False, separators=(",", ":")).encode("utf-8")
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
        if n > MAX_BODY_BYTES:
            self.close_connection = True
            raise _BodyTooLarge("request body too large: %d bytes (cap %d)" % (n, MAX_BODY_BYTES))
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
                               "finished": st["finished"],
                               # Protocol version and engine version are separate: the former
                               # governs the shape of the API, the latter the shipped content.
                               "protocol": PROTOCOL_VERSION,
                               "engine_version": ENGINE_VERSION})
        if path == "/scratchpad":
            q = parse_qs(urlparse(self.path).query or "")
            count_only = (q.get("count", ["0"])[0] or "0").strip().lower() in ("1", "true", "yes", "on")
            items = ENGINE.scratch_read()
            if count_only:
                return self._send({"ok": True, "count": len(items)})
            return self._send({"ok": True, "items": items})
        if path == "/assist/pending":
            return self._send(ENGINE.assist_pending())
        if path == "/assist/inbox":
            return self._send(ENGINE.assist_inbox())
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
        except _BodyTooLarge as exc:
            try:
                self._send({"ok": False, "error": str(exc)}, 413)
            except Exception:
                pass
        except Exception as exc:
            try:
                self._send({"ok": False, "error": "Request failed: %s" % exc}, 500)
            except Exception:
                pass

    def _route_post(self, path, b):
        # Activity is recorded by the engine methods themselves (see
        # tm_engine._writing). The HTTP layer no longer keeps a second list,
        # so a new write endpoint cannot be forgotten and silently kill players.
        if path == "/open":
            return self._send(ENGINE.open_position(b.get("pair"), b.get("side"),
                                                   b.get("lots"), b.get("leverage")))
        if path == "/close":
            return self._send(ENGINE.close_position(b.get("pair"), b.get("lots")))
        if path == "/close_all":
            return self._send(ENGINE.close_all())
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
            threading.Timer(0.3, _hard_exit).start()
            return
        if path == "/trader":
            return self._send(ENGINE.set_trader(b.get("name")))
        if path == "/scratchpad":
            if b.get("clear") is True or str(b.get("clear", "")).strip().lower() in ("1", "true", "yes", "on"):
                return self._send(ENGINE.scratch_clear())
            return self._send(ENGINE.scratch_append(b.get("text")))
        if path == "/assist/enable":
            return self._send(ENGINE.assist_enable())
        if path == "/assist/ask":
            return self._send(ENGINE.assist_ask(b.get("text")))
        if path == "/assist/reply":
            return self._send(ENGINE.assist_reply(b.get("ticket"), b.get("text")))
        if path == "/assist/reject":
            return self._send(ENGINE.assist_reject(b.get("ticket")))
        if path == "/reset":
            return self._send(ENGINE.reset())
        if path == "/pause":
            return self._send(ENGINE.pause())
        if path == "/begin":
            return self._send(ENGINE.begin())
        if path == "/fastforward":
            return self._send(ENGINE.fast_forward(b.get("seconds")))
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
        # After the target is hit the match keeps running, but there is no reason to wait out
        # the wall clock: prices are tick-driven, so speeding up changes no random outcome.
        # TM_TAIL_SPEED overrides the multiplier (set 1 for the real pace).
        speed = 1.0
        try:
            if getattr(ENGINE.s, "hit_at_tick", None) is not None:
                speed = max(1.0, float(os.environ.get("TM_TAIL_SPEED") or TAIL_SPEED))
        except Exception:
            speed = 1.0
        time.sleep(TICK_SECONDS / speed)
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


class _Server(ThreadingHTTPServer):
    """Concurrency settings.

    ThreadingHTTPServer's default backlog is 5. With the spectator polling every 300 ms,
    external scripts, and the assist poll all hitting at once, an overflowing accept queue
    drops the SYN and the client sits there until its 3 s timeout -- which shows up as
    "service not responding" even though the service never went down.
    """
    daemon_threads = True
    allow_reuse_address = True
    request_queue_size = 64


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
    srv = _Server((host, port), Handler)
    SERVER = srv
    print("Tokens Trading Market started: http://%s:%d" % (host, port), flush=True)
    try:
        srv.serve_forever()
    except KeyboardInterrupt:
        pass
