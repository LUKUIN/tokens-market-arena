# -*- coding: utf-8 -*-
"""Regression tests for /state payload sizing and fastforward starvation.

Context: the spectator polls /state every 300 ms.
  * The old code shipped price_history (up to 2000 points per pair) and equity_curve
    (2000 points) in full; the payload grew linearly with match length, and so did
    serialisation, parsing and rendering cost.
  * The old code called _metrics() twice inside the return dict, recomputing MDD/Sharpe
    twice per poll for nothing.
  * The old fast_forward() held LOCK for all 60 ticks, blocking every reader.
Together those made the spectator banner say "service not responding" while the
service itself was alive and ticking.

Only two testable contracts are pinned here: the export caps, and that readers are
not starved during a fast-forward.
"""

import os
import sys
import threading
import time
import unittest

sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "src"))

import tm_engine as T  # noqa: E402


class _Base(unittest.TestCase):
    def setUp(self):
        import shutil
        import tempfile
        self.home = tempfile.mkdtemp(prefix="tmpayload_")
        self.addCleanup(shutil.rmtree, self.home, True)
        self.e = T.Engine(self.home)
        self.e.roll_stop()

    def long_curve(self, n=1500):
        return [{"tick": i, "equity": 1000000.0 + (i % 50)} for i in range(n)]


class TestStatePayloadLimits(_Base):
    def test_curve_export_is_capped(self):
        """/state only ships the tail; the engine must keep the full curve for reports."""
        self.e.s["equity_curve"] = self.long_curve(1500)
        st = self.e.state()
        self.assertLessEqual(len(st["equity_curve"]), T.STATE_CURVE_POINTS)
        self.assertEqual(len(self.e.s["equity_curve"]), 1500, "internal curve must not be truncated")

    def test_price_history_export_is_capped(self):
        """Per-pair mini sparklines ship only the tail, never the whole 2000 points."""
        self.e.s["price_history"]["AURA/CORE"] = [100.0 + i * 0.01 for i in range(1500)]
        st = self.e.state()
        self.assertLessEqual(len(st["price_history"]["AURA/CORE"]), T.STATE_HISTORY_POINTS)
        self.assertEqual(len(self.e.s["price_history"]["AURA/CORE"]), 1500)

    def test_history_off_still_empty(self):
        """?history=0 semantics must not change: still empty."""
        st = self.e.state(include_history=False, include_curve=False)
        self.assertEqual(st["price_history"], {})
        self.assertEqual(st["equity_curve"], [])

    def test_metrics_computed_once_per_state(self):
        """MDD/Sharpe must be computed once per /state - doing it twice is pure waste."""
        calls = {"n": 0}
        orig = self.e._metrics

        def counting(*a, **kw):
            calls["n"] += 1
            return orig(*a, **kw)

        self.e._metrics = counting
        self.e.s["equity_curve"] = self.long_curve(400)
        self.e.state()
        self.assertEqual(calls["n"], 1, "state() called _metrics %d times, expected 1" % calls["n"])


class TestFastForwardYieldsLock(_Base):
    def test_readers_are_not_starved_by_fast_forward(self):
        """While fast-forwarding 60 ticks, another thread reading /state must not stall >1 s."""
        worst = [0.0]
        stop = [False]

        def reader():
            while not stop[0]:
                t0 = time.time()
                self.e.state(include_history=False, include_events=False)
                worst[0] = max(worst[0], time.time() - t0)
                time.sleep(0.01)

        th = threading.Thread(target=reader)
        th.start()
        try:
            r = self.e.fast_forward(300)
        finally:
            stop[0] = True
            th.join(timeout=5)
        self.assertTrue(r.get("ok"), r)
        self.assertGreater(r.get("ticks", 0), 0)
        self.assertLess(worst[0], 1.0,
                        "reader starved for %.2f s during fastforward; the spectator would "
                        "call the service dead" % worst[0])


if __name__ == "__main__":
    unittest.main(verbosity=2)
