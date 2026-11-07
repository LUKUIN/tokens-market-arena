# -*- coding: utf-8 -*-
"""结算、清算与成本模型的不变量测试。

跑法（仓库根目录）：
    python -m unittest discover -s tests -v

这些用例守护的是三条硬规则：
1. 本局结束时，任何交易限制都不能阻止持仓被清算；清算失败必须显式暴露。
2. 普通平仓、爆仓强平、结算清算走同一条成交成本路径（点差 + 滑点 + 手续费）。
3. 报告能重算账本：每一笔余额变化都能在成交流水里找到出处。
"""

import copy
import os
import random
import sys
import tempfile
import unittest

sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "src"))

import tm_engine as T  # noqa: E402


class EngineCase(unittest.TestCase):
    def make(self):
        home = tempfile.mkdtemp(prefix="tmtest_")
        eng = T.Engine(home)
        eng.roll_stop()
        return eng

    def trading_delta(self, eng, pos):
        """按 close_position 的算法算一笔平仓对余额的影响，不改状态。"""
        fill, half, slip = eng._close_fill(pos["pair"], pos["side"], pos["lots"])
        pnl = eng._position_pnl(pos, fill)
        fee = pos["lots"] * T.LOTS_SIZE * fill * T.FEE_RATE * eng._mod("fee_mult")
        return pnl - fee, fill, half, slip


class TestEndSessionSettlement(EngineCase):
    def test_settlement_not_blocked_by_halt_close(self):
        """交易所维护（halt_close_until）期间结束本局，持仓仍必须清零。"""
        eng = self.make()
        eng.open_position("FROST/CORE", "LONG", 5, 20)
        eng.s["halt_close_until"] = eng.s["tick"] + 999
        self.assertTrue(eng.s["positions"], "前置条件：应有持仓")

        out = eng._end_session("测试：维护期结算")

        self.assertEqual(eng.s["positions"], [], "结算后不得残留持仓")
        self.assertTrue(out["settled"], "settled 必须为 True")
        self.assertEqual(out["warnings"], [], "不应产生告警")

    def test_settlement_not_blocked_by_halt_orders(self):
        """熔断停市（halt_until）期间结束本局，同样必须清算。"""
        eng = self.make()
        eng.open_position("AURA/CORE", "SHORT", 4, 20)
        eng.s["halt_until"] = eng.s["tick"] + 999

        out = eng._end_session("测试：熔断期结算")

        self.assertEqual(eng.s["positions"], [])
        self.assertTrue(out["settled"])

    def test_final_equity_has_no_unrealized_pnl(self):
        """结算后的最终权益必须等于现金减欠款，不含浮动盈亏。"""
        eng = self.make()
        eng.open_position("TIDE/CORE", "LONG", 6, 20)
        eng.s["halt_close_until"] = eng.s["tick"] + 999

        out = eng._end_session("测试：最终权益口径")

        self.assertAlmostEqual(eng._total_upnl(), 0.0, places=6)
        expected = eng.s["balance"] - eng.s["loan"]["balance"]
        self.assertAlmostEqual(out["final_equity"], expected, places=2)

    def test_loan_settled_at_end(self):
        """有借款时结束本局，欠款必须清零。"""
        eng = self.make()
        eng.open_position("AMBER/CORE", "LONG", 3, 20)
        eng.s["loan"]["balance"] = 50000.0
        eng.s["loan"]["borrowed"] = 50000.0

        out = eng._end_session("测试：贷款结算")

        self.assertEqual(eng.s["loan"]["balance"], 0.0)
        self.assertEqual(eng.s["positions"], [])
        self.assertTrue(out["settled"])


class TestCostModelUnified(EngineCase):
    def test_blowup_applies_spread_and_slip(self):
        """爆仓强平必须扣点差与滑点，不能只扣手续费。"""
        eng = self.make()
        eng.open_position("TIDE/CORE", "LONG", 10, 20)
        mid = eng.s["prices"]["TIDE/CORE"]

        eng._blowup()

        closes = [t for t in eng.s["trades"] if t.get("type") == "close"]
        self.assertEqual(len(closes), 1, "强平必须写入成交流水")
        rec = closes[0]
        self.assertTrue(rec.get("forced"), "强平记录应带 forced 标记")
        self.assertGreater(rec["spread_cost"], 0.0, "强平必须计点差")
        self.assertGreater(rec["slip_cost"], 0.0, "强平必须计滑点")
        self.assertLess(rec["fill"], mid, "LONG 平仓成交价必须低于中间价")

    def test_blowup_matches_close_cost(self):
        """同价同仓：爆仓与正常平仓的成交成本必须完全一致。

        两个引擎必须共用同一份局面（难度决定流动性，流动性决定滑点），
        所以这里直接深拷贝 state，而不是各跑一遍随机开局。
        """
        eng_a = self.make()
        eng_a.open_position("NEON/CORE", "LONG", 8, 20)
        pos_a = dict(eng_a.s["positions"][0])
        close_delta = self.trading_delta(eng_a, pos_a)[0]

        eng_b = self.make()
        eng_b.s = copy.deepcopy(eng_a.s)
        eng_b._blowup()
        blow_delta = eng_b.s["balance"] - eng_a.s["balance"]

        self.assertAlmostEqual(blow_delta, close_delta, places=2)

    def test_blowup_short_fill_above_mid(self):
        """空头平仓成交价必须高于中间价。"""
        eng = self.make()
        eng.open_position("ASH/CORE", "SHORT", 5, 20)
        mid = eng.s["prices"]["ASH/CORE"]

        eng._blowup()

        rec = [t for t in eng.s["trades"] if t.get("type") == "close"][0]
        self.assertGreater(rec["fill"], mid)


class TestLedgerTraceable(EngineCase):
    def test_every_balance_change_has_a_trade_row(self):
        """余额变化必须能被成交流水的 pnl/fee 之和重建。"""
        eng = self.make()
        start = eng.s["balance"]
        eng.open_position("FROST/CORE", "LONG", 5, 20)
        for _ in range(3):
            eng.tick()
        eng.close_position("FROST/CORE", None)

        trades = eng.s["trades"]
        opened = [t for t in trades if t.get("type") == "open"]
        closed = [t for t in trades if t.get("type") == "close"]
        self.assertEqual(len(opened), 1)
        self.assertEqual(len(closed), 1)

        net = (sum(t.get("pnl", 0.0) for t in trades)
               - sum(t.get("fee", 0.0) for t in trades)
               - eng.s.get("total_swap", 0.0))
        # 成交流水按分位记录，重算允许分位舍入误差
        self.assertAlmostEqual(eng.s["balance"] - start, net, places=1)

    def test_metrics_counts_forced_closes(self):
        """报告指标必须单独统计强平笔数。"""
        eng = self.make()
        eng.open_position("LUMEN/CORE", "LONG", 5, 20)
        eng._blowup()

        m = eng._metrics()
        self.assertEqual(m["forced_n"], 1)
        self.assertEqual(m["trades_n"], 1)

    def test_normal_settlement_is_not_counted_as_forced(self):
        """正常结算清仓不属于爆仓强平，不能计入「其中强制平仓」。"""
        eng = self.make()
        eng.open_position("TIDE/CORE", "LONG", 5, 20)

        eng._end_session("测试：正常结算")

        m = eng._metrics()
        self.assertEqual(m["forced_n"], 0, "正常结算不应计为强平")
        self.assertEqual(m["trades_n"], 1)

    def test_state_exposes_settlement_result(self):
        """结算结果必须能从 /state 读到，而不是只写在报告里。"""
        eng = self.make()
        eng.open_position("TIDE/CORE", "LONG", 5, 20)

        eng._end_session("测试：state 可见性")

        st = eng.state(include_history=False, include_events=False)
        self.assertIsNotNone(st["settlement"], "结算后 state 应带 settlement")
        self.assertTrue(st["settlement"]["settled"])
        self.assertEqual(st["settlement"]["warnings"], [])



class TestSeedReproducible(EngineCase):
    def test_same_seed_same_market(self):
        """同一 seed 必须复现同一市场：这是报告里写「TM_SEED=… 可复现」的前提。"""
        a = T._new_session(20261107)
        b = T._new_session(20261107)
        self.assertEqual(a["prices"], b["prices"])
        self.assertEqual(a["news_rate"], b["news_rate"])
        self.assertEqual(a["roll_phase"], b["roll_phase"])

    def test_session_records_seed_that_drives_state(self):
        """本局记录的 seed 必须真正控制随机流。"""
        random.seed(1234567)
        eng = self.make()
        seed = eng.s["seed"]

        random.seed(seed)  # 手动对齐到同一个 seed
        replay = T._new_session(seed)
        self.assertEqual(eng.s["prices"], replay["prices"])

    def test_reset_produces_reproducible_run(self):
        """reset 之后同一 seed 仍能复现（全局 random 流不允许跨局漂移）。"""
        eng = self.make()
        eng.reset()

        replay = T._new_session(eng.s["seed"])
        self.assertEqual(eng.s["prices"], replay["prices"])


if __name__ == "__main__":
    unittest.main(verbosity=2)
