# -*- coding: utf-8 -*-
"""Tokens 交易市场 —— HTTP 服务

端点：
    GET  /rules            规则
    GET  /state            账户、持仓、贷款、行情、历史
    GET  /prices           报价
    POST /open             开仓
    POST /close            平仓
    POST /close_all        全平
    POST /loan             借款 {"amount": 500000}（上浮比例借款时才抽定，这是代价）
    POST /repay            还款 {"amount": 500000}（省略 amount 则全额）
    POST /quit             结束本局
    POST /reset            重开一局
    GET  /health           存活探测
"""

import json
import os
import socket
import threading
import time
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from urllib.parse import urlparse, parse_qs

from tm_engine import Engine, TICK_SECONDS

HOME = os.path.join(os.path.dirname(os.path.abspath(__file__)), "data")
ENGINE = None
SERVER = None


MAX_BODY_BYTES = 1 << 20


class _BodyTooLarge(ValueError):
    pass


class _InvalidBody(ValueError):
    pass


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
        try:
            length = int(self.headers.get("Content-Length") or 0)
        except ValueError as exc:
            raise _InvalidBody("请求体必须是 UTF-8 JSON 对象") from exc
        if length < 0 or self.headers.get("Transfer-Encoding"):
            raise _InvalidBody("请求体必须是 UTF-8 JSON 对象")
        if length == 0:
            return {}
        if length > MAX_BODY_BYTES:
            raise _BodyTooLarge("请求体过大: %d > %d" % (length, MAX_BODY_BYTES))
        body = self.rfile.read(length)
        if len(body) != length:
            raise _InvalidBody("请求体必须是 UTF-8 JSON 对象")
        try:
            obj = json.loads(body.decode("utf-8"))
        except (UnicodeError, ValueError, RecursionError) as exc:
            raise _InvalidBody("请求体必须是 UTF-8 JSON 对象") from exc
        if not isinstance(obj, dict):
            raise _InvalidBody("请求体必须是 UTF-8 JSON 对象")
        return obj

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
        return self._send({"ok": False, "error": "未知端点：%s" % path}, 404)

    def do_POST(self):
        try:
            self._note()
            path = urlparse(self.path).path.rstrip("/") or "/"
            b = self._body()
            return self._route_post(path, b)
        except (_InvalidBody, _BodyTooLarge) as exc:
            self.close_connection = True
            self._send({"ok": False, "error": str(exc)}, 413 if isinstance(exc, _BodyTooLarge) else 400)
        except Exception as exc:
            try:
                self._send({"ok": False, "error": "请求处理失败：%s" % exc}, 500)
            except Exception:
                pass

    def _route_post(self, path, b):
        trade = {
            "/open": (ENGINE.open_position, ("pair", "side", "lots", "leverage")),
            "/close": (ENGINE.close_position, ("pair", "lots", "side")),
            "/close_all": (ENGINE.close_all, ()),
            "/loan": (ENGINE.borrow, ("amount",)),
            "/repay": (ENGINE.repay, ("amount",)),
        }.get(path)
        if trade is not None:
            action, fields = trade
            result = action(*(b.get(field) for field in fields),
                            request_id=self.headers.get("Idempotency-Key"),
                            expected_session=b.get("session_id"))
            code = {"session_mismatch": 409, "idempotency_conflict": 409,
                    "invalid_idempotency_key": 400}.get(result.get("code"), 200)
            return self._send(result, code)
        if path == "/quit":
            resp = ENGINE.quit_session()
            try:
                return self._send(resp)
            finally:
                if resp.get("ok"):
                    threading.Timer(3.0, self.server.shutdown).start()
        if path == "/shutdown":
            # 立即停止服务（不结算、不清数据），供界面上的「结束相关进程」按钮使用。
            # 但「非正常退出」也要在 reports/ 里留一份快照，方便事后翻账。
            try:
                ENGINE.abnormal_exit_report("结束相关进程")
            except Exception:
                pass
            self._send({"ok": True, "msg": "服务已停止（已生成异常退出报告）"})
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
        if path == "/challenge/accept":
            return self._send(ENGINE.challenge_accept())
        if path == "/challenge/decline":
            return self._send(ENGINE.challenge_decline())
        if path == "/special":
            return self._send(ENGINE.set_special(b.get("name"), b.get("on")))
        if path == "/slot":
            return self._send(ENGINE.slot(b.get("amount")))
        return self._send({"ok": False, "error": "未知端点：%s" % path}, 404)



def _auto_tick():
    while True:
        time.sleep(TICK_SECONDS)
        try:
            st = ENGINE.tick()
            if isinstance(st, dict) and st.get("finished"):
                # 本局已结算（时间为负/超过时限）：与 /quit 一致，服务随之退出
                # ——「结束就是结束」，不再自动开新局，也不留空转的服务。
                threading.Timer(3.0, lambda: SERVER and SERVER.shutdown()).start()
                return
        except Exception:
            pass


def _roll_printer():
    """盲盒倒计时打印：每秒一行，定档后打印两行结果。

    只给剩余时间和「已定格」标记，不给当前编号 —— 否则 AI 就能挑档位。
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
                    print("  " + "━" * 46, flush=True)
                    print("   难度定档：黑天鹅 %s ｜ 流动性 %s" % (r["gap"], r["liq"]), flush=True)
                    print("   每 tick %.2f%% 跳空   ｜  20M 名义往返约 %.1f%%" % (
                        r["gap_chance"] * 100,
                        14.0 * (8_000_000.0 / max(1.0, r["liquidity"]))), flush=True)
                    print("  " + "━" * 46, flush=True)
                    printed_stop = True
                _t.sleep(2.0)
                continue
            left = float(st.get("roll_left") or 0.0)
            if left > 0:
                print("  难度抽选中… 剩余 %.1f 秒（POST /roll/stop 可提前定格）" % left,
                      end=chr(13), flush=True)
        except Exception:
            pass
        _t.sleep(1.0)


class _Server(ThreadingHTTPServer):
    allow_reuse_address = os.name != "nt"

    def server_bind(self):
        if os.name == "nt":
            self.socket.setsockopt(socket.SOL_SOCKET, socket.SO_EXCLUSIVEADDRUSE, 1)
        super().server_bind()


def serve(host="127.0.0.1", port=8734, *, started=None):
    try:
        srv = _Server((host, port), Handler)
    except OSError as exc:
        if started is None:
            raise
        started.set_exception(exc)
        return
    global ENGINE, SERVER
    try:
        ENGINE = Engine(HOME)
    except Exception as exc:
        srv.server_close()
        if started is None:
            raise
        started.set_exception(exc)
        return
    SERVER = srv
    # 人类版：服务起来后由 tm_watch 走「分辨率 → 难度盲盒 → 规则窗 → 主界面」，
    # 盲盒本身也是 GUI 里的按钮触发的（POST /roll/start、/roll/stop）。
    # 这里不主动 start_roll，避免服务先于窗口开始计时。
    print("")
    print("  " + "-" * 58)
    print("   服务已就绪，等待游戏窗口连接。")
    print("   若窗口没有自动出现，请回到启动它的命令行查看提示。")
    print("  " + "-" * 58)
    print("")
    threading.Thread(target=_auto_tick, daemon=True).start()
    threading.Thread(target=_roll_printer, daemon=True).start()
    print("Tokens 交易市场已启动： http://%s:%d" % (host, srv.server_port), flush=True)
    if started is not None:
        started.set_result(None)
    try:
        srv.serve_forever()
    except KeyboardInterrupt:
        pass
    finally:
        srv.server_close()
