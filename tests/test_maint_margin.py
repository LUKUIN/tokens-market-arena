# -*- coding: utf-8 -*-
"""v1.2.17: maintenance margin on notional exposure, so high leverage is no longer free.

Background: margin_level used to be equity / (notional / leverage). At 1000x,
34 lots of ~5.018M notional tied up only 5,019 in margin, so at equity 420K the ratio
still read 8,370% and neither the margin call (100%) nor the stop-out (50%) ever fired.

After: maintenance margin = notional exposure x MAINT_MARGIN_RATE (10%), and opening an
order must leave at least 150% behind.
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
        """34 lots at 1000x: at equity 420K the account must already be in margin call."""
        sym = "AURA/CORE"
        self.set_price(sym, 147.6040)
        r = self.e.open_position(sym, "LONG", 34, 1000)
        self.assertTrue(r.get("ok"), r)

        # open: notional ~5.019M, maintenance ~502K, equity ~999K -> ~199%
        ml_open = self.e.margin_level()
        self.assertGreater(ml_open, 1.8)
        self.assertLess(ml_open, 2.2)

        # price 130.5 (-11.6%): equity ~418K, maintenance ~444K -> ~94%
        self.set_price(sym, 130.5)
        ml_trough = self.e.margin_level()
        self.assertLess(ml_trough, T.MARGIN_CALL_RATIO,
                        "the trough must break the call line, otherwise high leverage stays free")
        self.assertGreater(ml_trough, T.STOP_OUT_RATIO)

    def test_margin_call_then_stop_out(self):
        sym = "AURA/CORE"
        self.set_price(sym, 147.6040)
        self.assertTrue(self.e.open_position(sym, "LONG", 34, 1000).get("ok"))

        self.set_price(sym, 130.5)
        self.e.s["tick"] = 10
        self.e._check_margin()
        self.assertTrue(self.events("margin_call"), "94% should trigger a margin call")

        self.set_price(sym, 124.0)
        self.e.s["tick"] += 1
        self.e._check_margin()
        self.assertTrue(self.e.s.get("blowups"), "below 50% must liquidate immediately")
        self.assertEqual(self.e.s["positions"], [])

    def test_low_leverage_is_unaffected(self):
        """1 lot at 20x: notional ~148K, maintenance ~14.8K, level ~6,700%."""
        sym = "AURA/CORE"
        self.set_price(sym, 147.6040)
        self.assertTrue(self.e.open_position(sym, "LONG", 1, 20).get("ok"))
        self.assertGreater(self.e.margin_level(), 50)


class OpenGuardTest(_Base):
    def test_oversized_notional_is_rejected(self):
        """70 lots at 1000x = ~10.33M notional against 1M equity must not open."""
        sym = "AURA/CORE"
        self.set_price(sym, 147.6040)
        r = self.e.open_position(sym, "LONG", 70, 1000)
        self.assertFalse(r.get("ok"))
        self.assertIn("maintenance margin", r.get("error", "").lower())

    def test_boundary_around_ten_times_equity(self):
        """34 lots (~5x) may open; another 34 (stacking to ~10x) must be refused.

        Effective cap ~ equity / (maintenance rate x open threshold) = 1M / (10% x 1.5) ~ 6.7x.
        """
        sym = "AURA/CORE"
        self.set_price(sym, 147.6040)
        self.assertTrue(self.e.open_position(sym, "LONG", 34, 1000).get("ok"),
                        "5x notional, ~199% after opening, should be allowed")
        r = self.e.open_position(sym, "LONG", 34, 1000)
        self.assertFalse(r.get("ok"), "stacking to ~10x must be blocked by maintenance margin")
        self.assertIn("maintenance margin", r.get("error", "").lower())


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
        # the old "margin_used" keeps its own definition, for per-position cost display
        self.assertLess(st["margin_used"], 10_000)


if __name__ == "__main__":
    unittest.main()
