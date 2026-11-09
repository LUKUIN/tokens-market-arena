# -*- coding: utf-8 -*-
"""v1.2.19: /quit splits into "target reached - early exit" and "abandoned below target".

Rule basis (user decision, 2026-11-09):
  Stopping once you have made enough is skill; leaving before that is giving up. Both are
  allowed, but they must be recorded differently - otherwise "locked in a gain" and "gave up"
  look identical in the statistics and the report cannot explain how a match ended.
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
        self.home = tempfile.mkdtemp(prefix="tm_quit_")
        self.addCleanup(shutil.rmtree, self.home, True)
        self.e = T.Engine(self.home)
        self.e.s["difficulty"] = {"gap": 2, "liq": 1, "at": 0,
                                  "gap_pct": T.GAP_LEVELS[2][1],
                                  "liq_depth": T.LIQ_LEVELS[1][1]}
        self.e.s["begun"] = True
        self.e.s["paused"] = False
        self.e.s["unnamed"] = False
        self.tgt = self.e.s["target"]

    def set_cash(self, cash):
        self.e.s["balance"] = cash


class QuitSemanticsTest(_Base):
    def test_hit_target_quit_is_valid_exit(self):
        self.set_cash(self.tgt * 1.2)
        r = self.e.quit_session()
        self.assertTrue(r.get("ok"), r)
        self.assertEqual(r.get("reason"), "Target reached - early exit")
        self.assertTrue(r.get("hit_target"))

    def test_below_target_quit_is_abandon(self):
        self.set_cash(self.tgt * 0.8)
        r = self.e.quit_session()
        self.assertTrue(r.get("ok"), r)
        self.assertEqual(r.get("reason"), "Abandoned below target")
        self.assertFalse(r.get("hit_target"))

    def test_exactly_at_target_counts_as_hit(self):
        self.set_cash(self.tgt)
        r = self.e.quit_session()
        self.assertEqual(r.get("reason"), "Target reached - early exit")
        self.assertTrue(r.get("hit_target"))


class HitAtTickTest(_Base):
    def test_hit_at_tick_recorded_once(self):
        self.e.s["tick"] = 40
        self.set_cash(self.tgt * 1.1)
        self.e.tick()
        first = self.e.s.get("hit_at_tick")
        self.assertIsNotNone(first)
        self.e.tick()
        self.assertEqual(self.e.s.get("hit_at_tick"), first)

    def test_giveback_after_hit_is_reported(self):
        self.set_cash(self.tgt * 1.2)
        self.e.s["hit_at_tick"] = 77
        self.set_cash(self.tgt * 0.7)
        r = self.e.quit_session()
        self.assertFalse(r.get("hit_target"))
        self.assertIn("Abandoned", r.get("reason", ""))
        end_events = [x for x in self.e.s.get("events", []) if x.get("kind") == "end"]
        self.assertTrue(end_events)
        self.assertIn("6:25", end_events[-1].get("text", ""))


class IdleSkipTest(_Base):
    def test_idle_abort_skipped_after_hit(self):
        old_min = T.IDLE_ABORT_MINUTES
        old_ticks = T.IDLE_ABORT_TICKS
        T.IDLE_ABORT_MINUTES = 1
        T.IDLE_ABORT_TICKS = 12
        self.addCleanup(setattr, T, "IDLE_ABORT_TICKS", old_ticks)
        self.addCleanup(setattr, T, "IDLE_ABORT_MINUTES", old_min)

        self.set_cash(self.tgt * 1.2)
        self.e.s["hit_at_tick"] = 1
        self.e.s["last_action_tick"] = 0
        self.e.s["tick"] = 40
        self.e.tick()
        self.assertFalse(self.e.s.get("finished"), "no idle abort after the target is hit")

        # Counter-check: without hit_at_tick (and below the target) it still fires
        self.e.s["hit_at_tick"] = None
        self.set_cash(self.tgt * 0.9)
        self.e.tick()
        self.assertTrue(self.e.s.get("finished"))


if __name__ == "__main__":
    unittest.main()
