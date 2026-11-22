# -*- coding: utf-8 -*-
"""v1.2.16: a reproducible difficulty slot (TM_ROLL_INDEX) and no seed leak mid-match.

Background: the slot used to follow only the wall clock at roll_stop
(`_roll_index = int(elapsed / 0.1 + phase) % 25`, one lap every 2.5 s), so the same
seed reopened a *different* slot and the report's "reproduce with TM_SEED=..." line
was a false promise for any match stopped by hand. This file pins three behaviours:

  * with TM_ROLL_INDEX set, the slot is fully determined by it, clock irrelevant;
  * without it, the clock still decides (old behaviour unchanged);
  * /state does not return the seed until the match is settled.

One regression worth stating: new fields must not consume randomness, otherwise the
price path of every historical seed shifts.
"""
import json
import os
import shutil
import sys
import tempfile
import time
import unittest
from unittest.mock import patch

sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "src"))

import tm_engine as T  # noqa: E402


class _Base(unittest.TestCase):
    def setUp(self):
        self._saved_idx = T._ROLL_INDEX_ENV
        self._saved_time = time.time
        self.home = tempfile.mkdtemp(prefix="tm_repro_")
        self.addCleanup(shutil.rmtree, self.home, True)

    def tearDown(self):
        T._ROLL_INDEX_ENV = self._saved_idx
        time.time = self._saved_time

    def make(self):
        return T.Engine(self.home)


class LockedIndexTest(_Base):
    def test_locked_index_wins_over_clock(self):
        T._ROLL_INDEX_ENV = "9"
        e = self.make()
        e.start_roll()
        time.time = lambda: 1e12          # any wall-clock value must lose
        r = e.roll_stop()
        self.assertEqual(r["index"], 9)
        self.assertEqual(r["gap"], T.GAP_LEVELS[4][0])
        self.assertEqual(r["liq"], T.LIQ_LEVELS[1][0])
        self.assertEqual(r["gap_chance"], T.GAP_LEVELS[4][1])
        self.assertEqual(r["liquidity"], T.LIQ_LEVELS[1][1])

    def test_locked_index_survives_reset(self):
        T._ROLL_INDEX_ENV = "3"
        e = self.make()
        e.start_roll()
        e.roll_stop()
        e.challenge_decline()   # These cases do not exercise challenges: decline the prompt and run a normal match
        e.reset(count=False)
        r = e.roll_stop()
        self.assertEqual(r["index"], 3)

    def test_explicit_roll_index_beats_env(self):
        T._ROLL_INDEX_ENV = "9"
        e = self.make()
        e.reset(count=False, roll_index=0)
        r = e.roll_stop()
        self.assertEqual(r["index"], 0)
        self.assertEqual(r["gap"], T.GAP_LEVELS[0][0])
        self.assertEqual(r["liq"], T.LIQ_LEVELS[0][0])

    def test_invalid_env_is_ignored(self):
        for bad in ["", "abc", "-1", "25", "999", "  "]:
            T._ROLL_INDEX_ENV = bad
            self.assertIsNone(T._roll_index_from_env(), bad)


class ClockIndexTest(_Base):
    def test_without_lock_clock_decides(self):
        T._ROLL_INDEX_ENV = ""
        e = self.make()
        e.s["roll_phase"] = 11.764222
        e.s["roll_started_at"] = 1000.0
        time.time = lambda: 1000.3        # 0.3s -> int(0.3/0.1 + 11.764) % 25 = 14
        r = e.roll_stop()
        self.assertEqual(r["index"], 14)
        self.assertEqual(r["gap"], T.GAP_LEVELS[4][0])
        self.assertEqual(r["liq"], T.LIQ_LEVELS[2][0])

    def test_clock_index_moves_with_stop_time(self):
        """Same seed, same phase, different stop time -> different slot."""
        T._ROLL_INDEX_ENV = ""
        e = self.make()
        e.s["roll_phase"] = 11.764222
        e.s["roll_started_at"] = 1000.0
        got = {}
        for t in (0.3, 1.0, 2.0, 30.0):
            time.time = lambda t=t: 1000.0 + t
            got[t] = e._roll_index()
        self.assertEqual(got[0.3], 14)
        self.assertEqual(got[1.0], 21)
        self.assertEqual(got[2.0], 6)
        self.assertNotEqual(len(set(got.values())), 1)


class SeedVisibilityTest(_Base):
    def test_state_hides_seed_until_finished(self):
        e = self.make()
        st = e.state()
        self.assertIn("seed", st, "the field stays, but its value must be None")
        self.assertIsNone(st["seed"])
        e.s["finished"] = True
        self.assertEqual(e.state()["seed"], e.s["seed"])

    def test_health_payload_has_no_seed(self):
        """/health picks a few fields; it must never dump the whole state."""
        e = self.make()
        st = e.state()
        payload = {"ok": True, "tick": st["tick"], "equity": st["equity"],
                   "finished": st["finished"],
                   "protocol": T.PROTOCOL_VERSION, "engine_version": T.ENGINE_VERSION}
        self.assertNotIn("seed", payload)


class ReportIndexTest(_Base):
    def test_roll_index_text(self):
        T._ROLL_INDEX_ENV = "9"
        e = self.make()
        e.start_roll()
        e.roll_stop()
        e.challenge_decline()   # These cases do not exercise challenges: decline the prompt and run a normal match
        self.assertEqual(e._roll_index_text(),
                         ("9", T.GAP_LEVELS[4][0], T.LIQ_LEVELS[1][0]))

    def test_roll_index_text_before_roll(self):
        e = self.make()
        self.assertEqual(e._roll_index_text(), ("—", "—", "—"))


class RandomStreamRegressionTest(_Base):
    def start_match(self, home):
        engine = T.Engine(home)
        engine.reset(count=False, seed=576407804, roll_index=12)
        engine.challenge_decline()
        engine.roll_stop()
        return engine

    def test_player_actions_do_not_move_the_market(self):
        with tempfile.TemporaryDirectory() as other_home:
            regular = self.start_match(self.home)
            with patch.dict(T._SPECIAL_CACHE, {"TM_SLOT": True, "TM_FR": True}):
                playing = self.start_match(other_home)
                self.assertTrue(playing.slot(1)["ok"])
                self.assertTrue(playing.borrow(1000)["ok"])
            for _ in range(5):
                regular.tick()
                playing.tick()
                self.assertEqual(regular.s["prices"], playing.s["prices"])
                self.assertEqual(regular.s["liquidity"], playing.s["liquidity"])

    def test_restart_restores_both_random_streams(self):
        with patch.dict(T._SPECIAL_CACHE, {"TM_SLOT": True}):
            engine = self.start_match(self.home)
            self.assertTrue(engine.slot(1)["ok"])
            engine.tick()

        with tempfile.TemporaryDirectory() as restart_home:
            shutil.copy(engine.path, restart_home)
            resumed = T.Engine(restart_home)
            self.assertFalse(resumed.s.get("rng_resumed"))
            for _ in range(5):
                engine.tick()
                resumed.tick()
                self.assertEqual(engine.s["prices"], resumed.s["prices"])
            self.assertTrue(engine.slot(1)["ok"])
            self.assertTrue(resumed.slot(1)["ok"])
            self.assertEqual(engine.s["special"]["slot_history"], resumed.s["special"]["slot_history"])

    def test_old_save_can_resume_with_an_explicit_replay_limit(self):
        engine = self.start_match(self.home)
        engine.tick()
        state = dict(engine.s)
        for key in ("market_rng_state", "player_rng_state", "_sig"):
            state.pop(key)
        state["_sig"] = T._sign(state)
        with open(engine.path, "w", encoding="utf-8") as save:
            json.dump(state, save)

        resumed = self.make()
        self.assertTrue(resumed.s["rng_resumed"])
        self.assertEqual(resumed.s["prices"], engine.s["prices"])
        self.assertEqual(resumed.s["tick"], 1)
        resumed.tick()
        self.assertEqual(resumed.s["tick"], 2)


if __name__ == "__main__":
    unittest.main()
