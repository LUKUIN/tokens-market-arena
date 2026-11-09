# -*- coding: utf-8 -*-
"""Invariant tests for settlement, liquidation and the cost model.

Run from the repository root:
    python -m unittest discover -s tests -v

These guard three hard rules:
1. Ending a run must clear every position no matter which trading halts are
   active, and a failed clearance must be reported explicitly.
2. Regular close, blow-up liquidation and end-of-run settlement share one
   cost path (spread + slippage + fees).
3. The report can rebuild the ledger: every balance change has a trade row.
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
        """Balance impact of closing this position, without mutating state."""
        fill, half, slip = eng._close_fill(pos["pair"], pos["side"], pos["lots"])
        pnl = eng._position_pnl(pos, fill)
        fee = pos["lots"] * T.LOTS_SIZE * fill * T.FEE_RATE * eng._mod("fee_mult")
        return pnl - fee, fill, half, slip


class TestEndSessionSettlement(EngineCase):
    def test_settlement_not_blocked_by_halt_close(self):
        """Ending a run during an exchange maintenance window still clears all positions."""
        eng = self.make()
        eng.open_position("FROST/CORE", "LONG", 5, 20)
        eng.s["halt_close_until"] = eng.s["tick"] + 999
        self.assertTrue(eng.s["positions"], "precondition: a position must exist")

        out = eng._end_session("test: settlement during maintenance")

        self.assertEqual(eng.s["positions"], [], "no position may survive settlement")
        self.assertTrue(out["settled"], "settled must be True")
        self.assertEqual(out["warnings"], [], "no warnings expected")

    def test_time_up_path_settles_even_during_halt(self):
        """Reaching 45:00 during exchange maintenance must still clear positions.

        Regression for the merged settlement path: the old tick() called
        close_position() directly, which the maintenance window refuses, and
        ignored the return value -- leaving positions on a "settled" run.
        """
        eng = self.make()
        eng.open_position("FROST/CORE", "LONG", 5, 20)
        eng.s["halt_close_until"] = eng.s["tick"] + 999
        eng.s["created_at"] -= T.SESSION_MINUTES * 60 + 1

        eng.tick()

        self.assertTrue(eng.s["finished"], "tick must finish the run")
        self.assertEqual(eng.s["positions"], [], "maintenance must not block the final clean-up")
        settle = eng.s.get("last_settle") or {}
        self.assertTrue(settle.get("settled"), "settled must be True")
        self.assertEqual(settle.get("warnings") or [], [])

    def test_settlement_not_blocked_by_halt_orders(self):
        """A circuit breaker (halt_until) must not block settlement either."""
        eng = self.make()
        eng.open_position("AURA/CORE", "SHORT", 4, 20)
        eng.s["halt_until"] = eng.s["tick"] + 999

        out = eng._end_session("test: settlement during a circuit breaker")

        self.assertEqual(eng.s["positions"], [])
        self.assertTrue(out["settled"])

    def test_final_equity_has_no_unrealized_pnl(self):
        """Final equity equals cash minus debt, with no floating P&L left."""
        eng = self.make()
        eng.open_position("TIDE/CORE", "LONG", 6, 20)
        eng.s["halt_close_until"] = eng.s["tick"] + 999

        out = eng._end_session("test: final equity definition")

        self.assertAlmostEqual(eng._total_upnl(), 0.0, places=6)
        expected = eng.s["balance"] - eng.s["loan"]["balance"]
        self.assertAlmostEqual(out["final_equity"], expected, places=2)

    def test_loan_settled_at_end(self):
        """With an outstanding loan, ending the run must leave zero debt."""
        eng = self.make()
        eng.open_position("AMBER/CORE", "LONG", 3, 20)
        eng.s["loan"]["balance"] = 50000.0
        eng.s["loan"]["borrowed"] = 50000.0

        out = eng._end_session("test: loan settlement")

        self.assertEqual(eng.s["loan"]["balance"], 0.0)
        self.assertEqual(eng.s["positions"], [])
        self.assertTrue(out["settled"])


class TestCostModelUnified(EngineCase):
    def test_blowup_applies_spread_and_slip(self):
        """Blow-up liquidation must charge spread and slippage, not just fees."""
        eng = self.make()
        eng.open_position("TIDE/CORE", "LONG", 10, 20)
        mid = eng.s["prices"]["TIDE/CORE"]

        eng._blowup()

        closes = [t for t in eng.s["trades"] if t.get("type") == "close"]
        self.assertEqual(len(closes), 1, "the forced close must be logged")
        rec = closes[0]
        self.assertTrue(rec.get("forced"), "forced close must carry the forced flag")
        self.assertGreater(rec["spread_cost"], 0.0, "spread must be charged")
        self.assertGreater(rec["slip_cost"], 0.0, "slippage must be charged")
        self.assertLess(rec["fill"], mid, "closing a LONG fills below mid")

    def test_blowup_matches_close_cost(self):
        """Same position, same price: blow-up and a manual close cost the same.

        Both engines must share an identical situation (difficulty drives
        liquidity, liquidity drives slippage), so the state is deep-copied
        instead of opening two random runs.
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
        """Closing a SHORT fills above mid."""
        eng = self.make()
        eng.open_position("ASH/CORE", "SHORT", 5, 20)
        mid = eng.s["prices"]["ASH/CORE"]

        eng._blowup()

        rec = [t for t in eng.s["trades"] if t.get("type") == "close"][0]
        self.assertGreater(rec["fill"], mid)


class TestLedgerTraceable(EngineCase):
    def test_every_balance_change_has_a_trade_row(self):
        """Balance changes must be rebuildable from pnl/fee in the trade log."""
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
        # Trade rows store amounts rounded to cents; allow cent-level drift
        self.assertAlmostEqual(eng.s["balance"] - start, net, places=1)

    def test_metrics_counts_forced_closes(self):
        """Report metrics must count forced liquidations separately."""
        eng = self.make()
        eng.open_position("LUMEN/CORE", "LONG", 5, 20)
        eng._blowup()

        m = eng._metrics()
        self.assertEqual(m["forced_n"], 1)
        self.assertEqual(m["trades_n"], 1)

    def test_normal_settlement_is_not_counted_as_forced(self):
        """A normal settlement close is not a blow-up and must not be counted as forced."""
        eng = self.make()
        eng.open_position("TIDE/CORE", "LONG", 5, 20)

        eng._end_session("test: normal settlement")

        m = eng._metrics()
        self.assertEqual(m["forced_n"], 0, "a normal settlement is not a forced close")
        self.assertEqual(m["trades_n"], 1)

    def test_state_exposes_settlement_result(self):
        """The settlement result must be readable from /state, not only from the report."""
        eng = self.make()
        eng.open_position("TIDE/CORE", "LONG", 5, 20)

        eng._end_session("test: state visibility")

        st = eng.state(include_history=False, include_events=False)
        self.assertIsNotNone(st["settlement"], "state must carry settlement after a run ends")
        self.assertTrue(st["settlement"]["settled"])
        self.assertEqual(st["settlement"]["warnings"], [])



class TestSeedReproducible(EngineCase):
    def test_same_seed_same_market(self):
        """One seed must reproduce one market: that is what the report promises."""
        a = T._new_session(20261107)
        b = T._new_session(20261107)
        self.assertEqual(a["prices"], b["prices"])
        self.assertEqual(a["news_rate"], b["news_rate"])
        self.assertEqual(a["roll_phase"], b["roll_phase"])

    def test_session_records_seed_that_drives_state(self):
        """The seed stored in the run must actually drive the random stream."""
        random.seed(1234567)
        eng = self.make()
        seed = eng.s["seed"]

        random.seed(seed)
        replay = T._new_session(seed)
        self.assertEqual(eng.s["prices"], replay["prices"])

    def test_reset_produces_reproducible_run(self):
        """After reset, the same seed still reproduces (no cross-run drift)."""
        eng = self.make()
        eng.reset()

        replay = T._new_session(eng.s["seed"])
        self.assertEqual(eng.s["prices"], replay["prices"])


if __name__ == "__main__":
    unittest.main(verbosity=2)
