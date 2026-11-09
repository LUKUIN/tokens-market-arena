# -*- coding: utf-8 -*-
"""v1.2.16：难度档位可复现（TM_ROLL_INDEX）+ 局中不泄露随机种子。

背景：报告的档位原先只由「叫停时刻」的墙钟决定
（`_roll_index = int(elapsed / 0.1 + phase) % 25`，2.5 秒转一圈），
同一 seed 重开必然抽到别的档位，报告里的「复现方式」对主动叫停的对局不成立。
本文件锁死三条行为：

  · 设了 TM_ROLL_INDEX，档位就完全由它决定，与墙钟无关；
  · 没设时仍走墙钟（旧行为不变）；
  · 对局中 /state 不返回 seed，结算后才返回。

另有一条回归：新增字段不得消耗随机数，否则同一 seed 的行情会整体错位。
"""
import os
import shutil
import sys
import tempfile
import time
import unittest

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
        # 把墙钟推到随便哪个位置，锁档都应该赢
        time.time = lambda: 1e12
        r = e.roll_stop()
        self.assertEqual(r["index"], 9)
        self.assertEqual(r["gap"], "极高")
        self.assertEqual(r["liq"], "正常")
        self.assertEqual(r["gap_chance"], T.GAP_LEVELS[4][1])
        self.assertEqual(r["liquidity"], T.LIQ_LEVELS[1][1])

    def test_locked_index_survives_reset(self):
        T._ROLL_INDEX_ENV = "3"
        e = self.make()
        e.start_roll()
        e.roll_stop()
        e.reset(count=False)
        r = e.roll_stop()
        self.assertEqual(r["index"], 3)

    def test_explicit_roll_index_beats_env(self):
        T._ROLL_INDEX_ENV = "9"
        e = self.make()
        e.reset(count=False, roll_index=0)
        r = e.roll_stop()
        self.assertEqual(r["index"], 0)
        self.assertEqual(r["gap"], "极低")
        self.assertEqual(r["liq"], "充裕")

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
        time.time = lambda: 1000.3          # 0.3s -> int(0.3/0.1 + 11.764) % 25 = 14
        r = e.roll_stop()
        self.assertEqual(r["index"], 14)
        self.assertEqual(r["gap"], "极高")
        self.assertEqual(r["liq"], "纤薄")

    def test_clock_index_moves_with_stop_time(self):
        """同一 seed、同一 phase，换个叫停时刻就换档 —— 这正是要锁档的原因。"""
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
        self.assertIn("seed", st, "接口应保留该字段，但值为 None")
        self.assertIsNone(st["seed"])
        e.s["finished"] = True
        self.assertEqual(e.state()["seed"], e.s["seed"])

    def test_health_payload_has_no_seed(self):
        """/health 只取少数字段，绝不能顺手把整份 state 塞出去。"""
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
        self.assertEqual(e._roll_index_text(), ("9", "极高", "正常"))

    def test_roll_index_text_before_roll(self):
        e = self.make()
        self.assertEqual(e._roll_index_text(), ("—", "—", "—"))


class RandomStreamRegressionTest(_Base):
    """锁档参数是「读环境变量」，不得插入任何 random 调用。"""

    def test_new_fields_do_not_shift_price_stream(self):
        T._ROLL_INDEX_ENV = ""
        seq = []
        for _ in range(2):
            home = tempfile.mkdtemp(prefix="tm_repro2_")
            self.addCleanup(shutil.rmtree, home, True)
            e = T.Engine(home)
            T.random.seed(576407804)
            e.s["began"] = e.s["begun"] = True
            e.s["paused"] = False
            for _tick in range(10):
                e._advance_prices()
            seq.append(tuple(round(e.s["prices"][k], 8) for k in sorted(e.s["prices"])))
        self.assertEqual(seq[0], seq[1])


if __name__ == "__main__":
    unittest.main()
