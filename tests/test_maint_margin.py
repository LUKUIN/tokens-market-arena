# -*- coding: utf-8 -*-
"""v1.2.17：维持保证金按名义敞口计，高杠杆不再「免费」的风险豁免。

背景：margin_level 原先 = 净值 ÷ 按杠杆折算的占用保证金。1000 倍杠杆下
34 手 / 501.8 万名义只占 5,019 元保证金，净值跌到 42 万时该比值仍有 8,370%，
追缴线（100%）与强平线（50%）一次都不会触发。实测两局豆包都用「单币满仓
+ 死扛」赢了，根因就在这里。

改后：维持保证金 = 名义敞口 × MAINT_MARGIN_RATE（10%），margin_level 的
分母换成它；开仓时还要求开完仍有 150% 的余量。
"""
import os
import shutil
import sys
import tempfile
import unittest

sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "src"))

import tm_engine as T  # noqa: E402


class _Base(unittest.TestCase):
    def setUp(self):
        self.home = tempfile.mkdtemp(prefix="tm_maint_")
        self.addCleanup(shutil.rmtree, self.home, True)
        self.e = T.Engine(self.home)
        self.e.s["difficulty"] = {"gap": 2, "liq": 1, "at": 0,
                                  "gap_pct": T.GAP_LEVELS[2][1],
                                  "liq_depth": T.LIQ_LEVELS[1][1]}
        self.e.s["begun"] = True
        self.e.s["paused"] = False

    def set_price(self, sym, price):
        self.e.s["prices"][sym] = price

    def events(self, kind):
        return [x for x in self.e.s.get("events", []) if x.get("kind") == kind]


class MarginLevelSemanticsTest(_Base):
    def test_no_position_returns_none(self):
        self.assertIsNone(self.e.margin_level())

    def test_high_leverage_no_longer_grants_immunity(self):
        """34 手 1000× 开仓后，净值跌回 42 万必须已经进入追缴区。"""
        sym = "AURA/CORE"
        self.set_price(sym, 147.6040)
        r = self.e.open_position(sym, "LONG", 34, 1000)
        self.assertTrue(r.get("ok"), r)

        # 开仓时：名义约 501.9 万，维持保证金约 50.2 万，净值约 99.9 万 -> 约 199%
        ml_open = self.e.margin_level()
        self.assertGreater(ml_open, 1.8)
        self.assertLess(ml_open, 2.2)

        # 价格跌到 130.5（约 -11.6%）：净值约 41.8 万，维持保证金约 44.4 万 -> 约 94%
        self.set_price(sym, 130.5)
        ml_trough = self.e.margin_level()
        self.assertLess(ml_trough, T.MARGIN_CALL_RATIO,
                        "谷底必须跌破追缴线，否则高杠杆仍是免死金牌")
        self.assertGreater(ml_trough, T.STOP_OUT_RATIO)

    def test_margin_call_then_stop_out(self):
        sym = "AURA/CORE"
        self.set_price(sym, 147.6040)
        self.assertTrue(self.e.open_position(sym, "LONG", 34, 1000).get("ok"))

        self.set_price(sym, 130.5)
        self.e.s["tick"] = 10
        self.e._check_margin()
        self.assertTrue(self.events("margin_call"), "跌到 94% 应触发追缴通知")

        self.set_price(sym, 124.0)
        self.e.s["tick"] += 1
        self.e._check_margin()
        self.assertTrue(self.e.s.get("blowups"), "跌破 50% 应直接强平")
        self.assertEqual(self.e.s["positions"], [])

    def test_low_leverage_is_unaffected(self):
        """1 手 20× 的常规仓位：名义约 14.8 万，维持保证金约 1.48 万，水平约 6,700%。"""
        sym = "AURA/CORE"
        self.set_price(sym, 147.6040)
        self.assertTrue(self.e.open_position(sym, "LONG", 1, 20).get("ok"))
        self.assertGreater(self.e.margin_level(), 50)


class OpenGuardTest(_Base):
    def test_oversized_notional_is_rejected(self):
        """70 手 1000× = 约 1,033 万名义，净值只有 100 万，必须开不出来。"""
        sym = "AURA/CORE"
        self.set_price(sym, 147.6040)
        r = self.e.open_position(sym, "LONG", 70, 1000)
        self.assertFalse(r.get("ok"))
        self.assertIn("维持保证金不足", r.get("error", ""))

    def test_boundary_around_ten_times_equity(self):
        """34 手约 5 倍名义可以开；再加 34 手叠到约 10 倍名义必须被拒。

        有效上限 ≈ 净值 ÷ (维持保证金率 × 开仓线) = 100 万 ÷ (10% × 1.5) ≈ 6.7 倍。
        """
        sym = "AURA/CORE"
        self.set_price(sym, 147.6040)
        self.assertTrue(self.e.open_position(sym, "LONG", 34, 1000).get("ok"),
                        "5 倍名义、开仓后约 199% 水平，应当允许")
        r = self.e.open_position(sym, "LONG", 34, 1000)
        self.assertFalse(r.get("ok"), "叠到约 10 倍名义应被维持保证金挡住")
        self.assertIn("维持保证金不足", r.get("error", ""))


class StateFieldTest(_Base):
    def test_state_exposes_maint_margin(self):
        sym = "AURA/CORE"
        self.set_price(sym, 147.6040)
        self.e.open_position(sym, "LONG", 34, 1000)
        st = self.e.state()
        self.assertIn("maint_margin", st)
        self.assertIn("maint_rate", st)
        self.assertAlmostEqual(st["maint_rate"], T.MAINT_MARGIN_RATE * 100, places=2)
        self.assertGreater(st["maint_margin"], 400_000)
        # 旧的「占用保证金」字段保留原口径，供报告展示单仓成本
        self.assertLess(st["margin_used"], 10_000)


if __name__ == "__main__":
    unittest.main()
