# -*- coding: utf-8 -*-
"""Regression tests for the idle abort (v1.2.13: engine-level, tick-based).

The original reason for this guard: a human double-clicks the AI launcher and
the match runs for 45 minutes with nobody trading.

Four directions must hold:
  · with nobody acting, the match must settle early;
  · with a real write action, it must never kill the contestant;
  · a failed request (bad parameters) must not keep the match alive;
  · read-only observation does not count, so slow thinking is never cut short.

One more hard constraint: the accounting must live in the engine. v1.2.12 put
the hook in the HTTP layer, so the headless baseline in bench.py was governed
by a different rule than a contestant over HTTP.
"""
import json
import os
import shutil
import sys
import tempfile
import unittest

sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "src"))

import tm_engine as T  # noqa: E402


class _IdleBase(unittest.TestCase):
    """Shrink the threshold to 1 minute so the decision fits in a few ticks."""

    def setUp(self):
        self._saved = (T.IDLE_ABORT_MINUTES, T.IDLE_ABORT_TICKS)
        T.IDLE_ABORT_MINUTES = 1
        T.IDLE_ABORT_TICKS = (1 * 60) // T.TICK_SECONDS
        self.addCleanup(self._restore)

    def _restore(self):
        T.IDLE_ABORT_MINUTES, T.IDLE_ABORT_TICKS = self._saved

    def make(self):
        home = tempfile.mkdtemp(prefix="tmidle_")
        self.addCleanup(shutil.rmtree, home, True)
        eng = T.Engine(home)
        eng.roll_stop()          # the clock only starts after the difficulty lock
        return eng

    def push_idle(self, eng):
        """Move the last action just past the threshold."""
        eng.s["last_action_tick"] = eng.s["tick"] - T.IDLE_ABORT_TICKS


class TestIdleAbort(_IdleBase):
    def test_idle_abort_triggers(self):
        """No action past the threshold must settle, with the reason recorded."""
        eng = self.make()
        self.push_idle(eng)
        eng.tick()
        self.assertTrue(eng.s["finished"])
        self.assertIn(str(T.IDLE_ABORT_MINUTES), eng.s["last_settle"]["reason"])

    def test_write_actions_reset_idle(self):
        """Every state-changing method refreshes the timer -- direct calls included."""
        cases = [
            ("open_position", lambda e: e.open_position("AURA/CORE", "LONG", 1, 20)),
            ("borrow", lambda e: e.borrow(100000)),
            ("fast_forward", lambda e: e.fast_forward(180)),
            ("scratch_append", lambda e: e.scratch_append("note")),
            ("set_trader", lambda e: e.set_trader("regression")),
            ("slot", lambda e: e.slot(10000)),
            ("assist_enable", lambda e: e.assist_enable()),
            ("close_all", lambda e: e.close_all()),
        ]
        for name, call in cases:
            eng = self.make()
            self.push_idle(eng)
            r = call(eng)
            self.assertIsNot(r.get("ok"), False, "%s failed: %s" % (name, r))
            self.assertEqual(eng.s["last_action_tick"], eng.s["tick"],
                             "%s did not refresh the idle timer" % name)
            eng.tick()
            self.assertFalse(eng.s["finished"], "killed the contestant after %s" % name)

    def test_failed_request_does_not_reset(self):
        """A request with bad parameters cannot keep the match alive."""
        eng = self.make()
        self.push_idle(eng)
        r = eng.open_position("NOT_A_PAIR", "LONG", 1, 20)
        self.assertIs(r.get("ok"), False)
        self.assertNotEqual(eng.s["last_action_tick"], eng.s["tick"])
        eng.tick()
        self.assertTrue(eng.s["finished"])

    def test_read_only_does_not_reset(self):
        """Read-only observation is not activity: waiting is a legal strategy."""
        eng = self.make()
        before = eng.s["last_action_tick"]
        eng.state()
        eng.rules()
        eng.state()
        self.assertEqual(eng.s["last_action_tick"], before)

    def test_rules_text_comes_from_engine(self):
        """/rules text shares its source with the decision: threshold, scope, read-only note."""
        eng = self.make()
        text = json.dumps(eng.rules(), ensure_ascii=False)
        self.assertIn(str(T.IDLE_ABORT_MINUTES), text)
        self.assertIn("Read-only", text)
        self.assertIn("slow thinking", text)


class TestIdleDisabled(unittest.TestCase):
    """Behaviour with the default (TM_IDLE_ABORT unset or 0)."""

    def setUp(self):
        self._saved = (T.IDLE_ABORT_MINUTES, T.IDLE_ABORT_TICKS)
        T.IDLE_ABORT_MINUTES = 0
        T.IDLE_ABORT_TICKS = 0
        self.addCleanup(self._restore)

    def _restore(self):
        T.IDLE_ABORT_MINUTES, T.IDLE_ABORT_TICKS = self._saved

    def test_no_abort_when_disabled(self):
        home = tempfile.mkdtemp(prefix="tmidleoff_")
        self.addCleanup(shutil.rmtree, home, True)
        eng = T.Engine(home)
        eng.roll_stop()
        for _ in range(200):
            eng.tick()
        self.assertFalse(eng.s["finished"])

    def test_rules_say_disabled(self):
        home = tempfile.mkdtemp(prefix="tmidleoff_")
        self.addCleanup(shutil.rmtree, home, True)
        eng = T.Engine(home)
        text = json.dumps(eng.rules(), ensure_ascii=False)
        self.assertIn("disabled", text)


if __name__ == "__main__":
    unittest.main()
