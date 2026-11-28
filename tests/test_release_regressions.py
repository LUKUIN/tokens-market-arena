import http.client
import importlib
import json
import os
from pathlib import Path
import sys
import tempfile
import threading
import unittest
from concurrent.futures import ThreadPoolExecutor
from contextlib import closing
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))
import tm_engine as engine


class SettlementRegression(unittest.TestCase):
    def setUp(self):
        self.home = self.enterContext(tempfile.TemporaryDirectory())
        self.enterContext(patch.dict(os.environ, {"TM_EVENTS": "0", "TM_TRADER": "TestModel-test-CLI"}))
        self.market = engine.Engine(self.home)
        self.market.challenge_decline()
        self.market.roll_stop()

    def test_partial_close_moves_only_the_closed_pnl_into_cash(self):
        pair = "AURA/CORE"
        for side, quote in (("LONG", 103.0), ("SHORT", 97.0)):
            with self.subTest(side=side):
                self.market.s["prices"][pair] = 100.0
                opened = self.market.open_position(pair, side, 4, 20)
                self.assertTrue(opened["ok"], opened)
                position, = self.market.s["positions"]
                entry = position["entry"]
                self.market.s["prices"][pair] = quote
                cash = self.market.s["balance"]
                for quantity in (1, 3):
                    result = self.market.close_position(pair, quantity, side)
                    self.assertTrue(result["ok"], result)
                    lot, = result["closed"]
                    direction = 1 if side == "LONG" else -1
                    expected = direction * (lot["fill"] - entry) * quantity * engine.LOTS_SIZE
                    self.assertAlmostEqual(lot["pnl"], expected, delta=0.03)
                    trade = self.market.s["trades"][-1]
                    cash += trade["pnl"] - trade["fee"]
                    self.assertAlmostEqual(self.market.s["balance"], cash, delta=0.03)
                self.assertEqual(self.market.s["positions"], [])

    def test_invalid_close_side_does_not_touch_positions(self):
        pair = "AURA/CORE"
        for side in ("LONG", "SHORT"):
            self.assertTrue(self.market.open_position(pair, side, 1, 20)["ok"])
        before = self.market.s["order_count"]
        self.assertFalse(self.market.close_position(pair, side="LON")["ok"])
        self.assertEqual(self.market.s["order_count"], before)
        self.assertEqual(len(self.market.s["positions"]), 2)
        self.assertTrue(self.market.close_position(pair, lots="0.0", side="long")["ok"])
        self.assertEqual([pos["side"] for pos in self.market.s["positions"]], ["SHORT"])

    def test_open_rejects_fill_below_maintenance_threshold(self):
        pair = "AURA/CORE"
        price, lots = 100.0, 4
        self.market.s["prices"][pair] = price
        gross = lots * engine.LOTS_SIZE * price
        required = gross * engine.MAINT_MARGIN_RATE * engine.OPEN_MARGIN_RATIO
        half_spread = self.market._eff_spread(pair) / 2
        with patch.object(self.market, "_slip_rate", return_value=0.01):
            fill = price * (1 + half_spread + 0.01)
            commission = lots * engine.LOTS_SIZE * fill * engine.FEE_RATE
            self.market.s["balance"] = required + commission + 1
            rejected = self.market.open_position(pair, "LONG", lots, 100)
            self.assertFalse(rejected["ok"], rejected)
            self.assertEqual(self.market.s["positions"], [])
            self.market.s["balance"] += 0.02 * gross
            self.assertTrue(self.market.open_position(pair, "LONG", lots, 100)["ok"])
            self.assertGreaterEqual(self.market.margin_level(), engine.OPEN_MARGIN_RATIO)

    def test_fast_forward_keeps_state_readable_and_rejects_overlap(self):
        between_steps = threading.Event()
        resume = threading.Event()

        def yield_step(_seconds):
            between_steps.set()
            if not resume.wait(5):
                raise TimeoutError("fast-forward wait")

        with patch.object(engine.time, "sleep", side_effect=yield_step), ThreadPoolExecutor(1) as pool:
            active = pool.submit(self.market.fast_forward, 180)
            try:
                self.assertTrue(between_steps.wait(5))
                state = self.market.state()
                self.assertFalse(state["ff"]["can3"])
                self.assertFalse(self.market.fast_forward(180)["ok"])
                self.assertFalse(self.market.reset()["ok"])
            finally:
                resume.set()
            result = active.result(10)
        self.assertTrue(result["ok"], result)
        self.assertEqual(result["ff"]["records"], [180])
        self.assertEqual(result["state"]["ff"], self.market.ff_plan())

    def test_fast_forward_used_seconds_visible_to_settlement(self):
        duration = engine.SESSION_MINUTES * 60
        self.market.s["created_at"] -= duration - 179
        reported = []
        with patch.object(self.market, "_write_report", side_effect=lambda *_, **__: reported.append(self.market.ff_plan()["used"])):
            result = self.market.fast_forward(180)
        self.assertFalse(result["ok"])
        self.assertTrue(result["state"]["finished"])
        self.assertEqual(result["seconds"], 180)
        self.assertEqual(reported, [180])
        self.assertEqual(result["ff"]["records"], [180])
        # The end-of-match report sees the completed jump through the same state.
        self.assertEqual(result["state"]["ff"]["used"], 180)

    def test_http_rejects_bad_body_and_only_stops_after_success(self):
        with patch.object(engine, "Engine", return_value=self.market):
            api = importlib.import_module("tm_api")
        self.market.s["balance"] = self.market.s["target"] * 1.2
        pair = "AURA/CORE"
        self.assertTrue(self.market.open_position(pair, "LONG", 1, 20)["ok"])
        with patch.object(api, "ENGINE", self.market), api.ThreadingHTTPServer(("127.0.0.1", 0), api.Handler) as server:
            worker = threading.Thread(target=server.serve_forever, daemon=True)
            worker.start()
            stopped = threading.Event()

            def request(method, path, body=None, headers=None):
                with closing(http.client.HTTPConnection("127.0.0.1", server.server_port, timeout=5)) as conn:
                    conn.request(method, path, body=body, headers=headers or {})
                    response = conn.getresponse()
                    return response.status, json.load(response)

            try:
                with patch.object(api.threading, "Timer") as timer:
                    timer.return_value.start.side_effect = stopped.set
                    session = self.market.s["session_id"]
                    for body in (b"{", b"[]", b"null"):
                        self.assertEqual(request("POST", "/reset", body)[0], 400)
                    self.assertEqual(self.market.s["session_id"], session)
                    oversized = {"Content-Length": str(api.MAX_BODY_BYTES + 1)}
                    self.assertEqual(request("POST", "/reset", headers=oversized)[0], 413)
                    status, rejected = request("POST", "/quit")
                    self.assertEqual(status, 200)
                    self.assertFalse(rejected["ok"])
                    timer.assert_not_called()
                    self.assertFalse(request("GET", "/state")[1]["finished"])
                    self.assertTrue(request("POST", "/close_all")[1]["ok"])
                    self.assertTrue(request("POST", "/quit")[1]["ok"])
                    self.assertTrue(stopped.wait(2))
                    timer.assert_called_once_with(3.0, server.shutdown)
            finally:
                server.shutdown()
                worker.join(5)
