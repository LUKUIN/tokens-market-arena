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
    POST /quit             结束本局（达标且有持仓会被拒，须先 /close_all）
    POST /reset            重开一局
    GET  /health           存活探测
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
    """结算后清掉本局临时文件（保留 reports/）。"""
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
    """硬退出前的收尾：先把封存的源码还原，再 os._exit。

    os._exit 跳过 atexit 与 finally；不在这里 unseal，下一次启动 import 到的就是
    诱饵，会立刻 sys.exit(1) 并打印「CHEATING DETECTED」，看起来像被误判作弊。
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

# 慢请求探针：下一次真的「服务暂断」时，能拿到时间与端点，而不是靠猜。
# 阈值 0.5 秒——观众席轮询超时是 3 秒，这里留足提前量。
SLOW_LOG = os.path.join(HOME, "slow.log")
SLOW_SECONDS = 0.5


def _note_slow(what, seconds):
    try:
        os.makedirs(HOME, exist_ok=True)
        with open(SLOW_LOG, "a", encoding="utf-8") as f:
            f.write("%s %.3fs %s\n" % (time.strftime("%Y-%m-%d %H:%M:%S"), seconds, what))
    except Exception:
        pass


class _BodyTooLarge(Exception):
    """请求体超过上限：映射为 HTTP 413，而不是 500。"""


class _InvalidBody(ValueError):
    pass


class Handler(BaseHTTPRequestHandler):
    server_version = "TokensMarket/2.0"

    def log_message(self, fmt, *args):
        pass

    def _send(self, obj, code=200):
        # 不带缩进：/state 每 300ms 就要传一次，indent=1 会让体积膨胀三成以上，
        # 解析端（观众席主线程）跟着多吃一份 CPU。接口消费者是程序，不需要花排版。
        body = json.dumps(obj, ensure_ascii=False, separators=(",", ":")).encode("utf-8")
        self.send_response(code)
        self.send_header("Content-Type", "application/json; charset=utf-8")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)
        _t0 = getattr(self, "_t0", None)
        if _t0 is not None:
            _dt = time.perf_counter() - _t0
            if _dt > SLOW_SECONDS:
                _note_slow("%s %s" % (getattr(self, "command", "?"), self.path), _dt)

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
        self._t0 = time.perf_counter()
        self._note()
        path = urlparse(self.path).path.rstrip("/") or "/"
        if path == "/health":
            st = ENGINE.state()
            return self._send({"ok": True, "tick": st["tick"], "equity": st["equity"],
                               "finished": st["finished"],
                               # 协议版本与引擎版本分开：前者管接口形状，后者管发布内容。
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
        return self._send({"ok": False, "error": "未知端点：%s" % path}, 404)

    def do_POST(self):
        self._t0 = time.perf_counter()
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
        # 「活动」由引擎方法自己记账（见 tm_engine._writing）：路由层不再维护
        # 第二份路径清单，也就不存在「新增写接口忘了加进来」这个漏点。
        if path == "/open":
            return self._send(ENGINE.open_position(b.get("pair"), b.get("side"),
                                                   b.get("lots"), b.get("leverage")))
        if path == "/close":
            return self._send(ENGINE.close_position(b.get("pair"), b.get("lots"), b.get("side")))
        if path == "/close_all":
            return self._send(ENGINE.close_all())
        if path == "/loan":
            return self._send(ENGINE.borrow(b.get("amount")))
        if path == "/repay":
            return self._send(ENGINE.repay(b.get("amount")))
        if path == "/quit":
            resp = ENGINE.quit_session()
            try:
                return self._send(resp)
            finally:
                if resp.get("ok"):
                    threading.Timer(3.0, self.server.shutdown).start()
        if path == "/shutdown":
            # 立即停止服务（不结算、不清数据），供观众席的「结束相关进程」按钮使用。
            # 但「非正常退出」也要在 reports/ 里留一份快照，方便事后翻账。
            try:
                ENGINE.abnormal_exit_report("结束相关进程")
            except Exception:
                pass
            self._send({"ok": True, "msg": "服务已停止（已生成异常退出报告）"})
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
        # 达标后比赛不结束，但不必干等满墙钟：行情按 tick 生成，加速只压缩等待时间，
        # 不改变任何随机结果。TM_TAIL_SPEED 可覆盖倍率（评测时可设 1 还原真实节奏）。
        speed = 1.0
        try:
            # ENGINE.s 是 dict，getattr(dict, "hit_at_tick") 恒为 None ——
            # 旧写法让达标后的 TAIL_SPEED 加速从来没生效过，看起来像「后半程卡住」。
            if (ENGINE.s or {}).get("hit_at_tick") is not None:
                speed = max(1.0, float(os.environ.get("TM_TAIL_SPEED") or TAIL_SPEED))
        except Exception:
            speed = 1.0
        time.sleep(TICK_SECONDS / speed)
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
    """并发参数。

    ThreadingHTTPServer 的默认 backlog 只有 5。观众席 300ms 轮询、外部脚本、
    观众席的求助轮询同时打进来时，accept 队列一溢出，新连接就被丢 SYN，
    客户端等满 3 秒超时——表现就是「服务无响应」，而服务本身一直活着。
    """
    daemon_threads = True
    allow_reuse_address = True
    request_queue_size = 64


def serve(host="127.0.0.1", port=8734):
    # AI 版没有 GUI 去触发盲盒，服务一起来就开始抽难度。
    # 人类版的 tm_watch 也会调 /roll/start，但 start_roll() 内部有幂等保护。
    try:
        ENGINE.start_roll()
    except Exception:
        pass

    print("")
    print("  " + "-" * 58)
    print("   草稿纸终端（可选）：对局中随时记录判断与对策")
    print("     python scratchpad.py \"你的想法\"   追加一条")
    print("     python scratchpad.py --list        查看已记内容")
    print("     python scratchpad.py --clear       清空")
    print("   结算时会并入 HTML 报告的「草稿纸」章节；不写也不影响结算。")
    print("  " + "-" * 58)
    print("")
    threading.Thread(target=_auto_tick, daemon=True).start()
    threading.Thread(target=_roll_printer, daemon=True).start()
    global SERVER
    srv = _Server((host, port), Handler)
    SERVER = srv
    print("Tokens 交易市场已启动： http://%s:%d" % (host, port), flush=True)
    try:
        srv.serve_forever()
    except KeyboardInterrupt:
        pass
