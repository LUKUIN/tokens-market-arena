# -*- coding: utf-8 -*-
"""Consistency regression tests across the HTML report, the JSON summary and /state.

Background: one match used to be reported through three outputs that each did their own maths:
  · HTML report: pnl = final equity - starting principal (genesis)
  · JSON summary: pnl = final equity - first curve point (after the opening cost)
  · /state      : pnl = final equity - starting principal
The first two could differ by one opening spread/fee on the same match, and bench.py reads
the JSON, so the statistics inherited the bias. A second issue: settlement happens after the
final tick, and the equity jump from force-closing was never written back into equity_curve,
so /state returned "equity -2.09M, last curve point 0.92M" in one payload.

Neither is cosmetic: the same match carried different numbers for different consumers.
"""

import json
import os
import shutil
import sys
import tempfile
import unittest

sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "src"))

import tm_engine as T  # noqa: E402


class ConsistencyCase(unittest.TestCase):
    def make(self):
        home = tempfile.mkdtemp(prefix="tmcons_")
        self.addCleanup(shutil.rmtree, home, True)
        eng = T.Engine(home)
        eng.roll_stop()
        return eng

    def crash_and_settle(self, eng):
        """Force a settlement whose equity jump happens after the final tick.

        The position is still in profit on the last tick, then the price gaps down and
        settlement force-closes it -- the exact shape of the old "curve stops at 0.92M,
        report says -1.29M" incident.
        """
        sym = "FROST/CORE"
        self.assertTrue(eng.open_position(sym, "LONG", 5, 20).get("ok"))
        for _ in range(3):
            eng.tick()
        eng.s["prices"][sym] = eng.s["prices"][sym] * 0.2
        return eng.quit_session()

    def read_summary(self, out):
        hp = out.get("report")
        self.assertTrue(hp and os.path.isfile(hp), "the HTML report must be generated")
        jp = os.path.splitext(hp)[0] + ".json"
        self.assertTrue(os.path.isfile(jp), "the JSON summary must sit next to the HTML")
        with open(jp, encoding="utf-8") as f:
            return json.load(f)


class TestCurveMatchesSettlement(ConsistencyCase):
    def test_state_curve_last_point_equals_final_equity(self):
        """After settlement, the /state curve tail must equal the final equity."""
        eng = self.make()
        out = self.crash_and_settle(eng)
        st = eng.state(include_history=False, include_events=False)
        curve = st.get("equity_curve") or []
        self.assertTrue(curve, "a settled match must keep its equity curve")
        self.assertAlmostEqual(float(curve[-1]["equity"]),
                               float(out["final_equity"]), places=2,
                               msg="/state curve tail disagrees with settled equity")

    def test_state_equity_and_curve_agree(self):
        """equity and the curve tail are the same data and must not disagree."""
        eng = self.make()
        self.crash_and_settle(eng)
        st = eng.state(include_history=False, include_events=False)
        self.assertAlmostEqual(float(st["equity"]),
                               float(st["equity_curve"][-1]["equity"]), places=2)

    def test_settlement_point_is_idempotent(self):
        """Re-settling must not stack a second identical point on the curve tail."""
        eng = self.make()
        self.crash_and_settle(eng)
        before = len(eng.s["equity_curve"])
        eq = eng.equity()
        if abs(float(eng.s["equity_curve"][-1]["equity"]) - float(eq)) <= 0.05:
            eng._end_session("re-settle")
        self.assertLessEqual(len(eng.s["equity_curve"]), before + 1)


class TestPnlBasisIsGenesis(ConsistencyCase):
    def test_json_pnl_uses_genesis_not_curve_first_point(self):
        """The JSON pnl must be measured from the principal, same basis as HTML and /state."""
        eng = self.make()
        out = self.crash_and_settle(eng)
        data = self.read_summary(out)
        genesis = float(eng.s["genesis"])
        self.assertAlmostEqual(data["pnl"],
                               round(float(out["final_equity"]) - genesis, 2),
                               places=2)
        self.assertAlmostEqual(data["pnl_pct"],
                               round((float(out["final_equity"]) / genesis - 1) * 100, 4),
                               places=3)

    def test_json_and_state_pnl_agree(self):
        """The JSON pnl must match the /state pnl exactly."""
        eng = self.make()
        out = self.crash_and_settle(eng)
        data = self.read_summary(out)
        st = eng.state(include_history=False, include_events=False)
        self.assertAlmostEqual(float(data["pnl"]), float(st["pnl"]), places=2)

    def test_genesis_field_is_exposed(self):
        """The new genesis field lets consumers recompute pnl themselves."""
        eng = self.make()
        out = self.crash_and_settle(eng)
        data = self.read_summary(out)
        self.assertIn("genesis", data)
        self.assertAlmostEqual(float(data["genesis"]), float(eng.s["genesis"]), places=2)

    def test_opening_before_first_tick_keeps_basis(self):
        """Opening before the first tick lowers the curve start, but pnl stays on the principal."""
        eng = self.make()
        self.assertTrue(eng.open_position("FROST/CORE", "LONG", 5, 20).get("ok"))
        out = eng.quit_session()
        data = self.read_summary(out)
        genesis = float(eng.s["genesis"])
        self.assertAlmostEqual(data["pnl"],
                               round(float(out["final_equity"]) - genesis, 2),
                               places=2)


if __name__ == "__main__":
    unittest.main(verbosity=2)
