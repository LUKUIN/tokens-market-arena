# -*- coding: utf-8 -*-
"""v1.2.19：/quit 分两种——达标离场（算达成）与主动弃权（不算）。

规则依据（用户 2026-11-09 拍板）：
  现实里赚够了收手是本事，没赚够就离场是认输；两者都允许，但必须分开记。
不区分的话，「浮盈锁定」和「认输」在统计里长得一模一样，评测无法解释结果。
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
        self.assertEqual(r.get("reason"), "达标离场")
        self.assertTrue(r.get("hit_target"))
        self.assertEqual(self.e.s["last_settle"]["reason"], "达标离场")

    def test_below_target_quit_is_abandon(self):
        self.set_cash(self.tgt * 0.8)
        r = self.e.quit_session()
        self.assertTrue(r.get("ok"), r)
        self.assertEqual(r.get("reason"), "主动弃权（未达标）")
        self.assertFalse(r.get("hit_target"))

    def test_hit_target_with_positions_refuses_quit(self):
        """达标后还挂着仓位就 /quit：拒绝结算，要求先 close_all 落袋。"""
        self.set_cash(self.tgt * 1.2)
        self.e.s["prices"]["AURA/CORE"] = 100.0
        ok = self.e.open_position("AURA/CORE", "LONG", 1, 20).get("ok")
        self.assertTrue(ok, "测试前置：应能开出一笔小仓位")

        r = self.e.quit_session()
        self.assertFalse(r.get("ok"))
        self.assertIn("close_all", r.get("error", ""))
        self.assertFalse(self.e.s.get("finished"), "被拒后本局应仍在进行")
        self.assertEqual(len(self.e.s["positions"]), 1)

        self.e.close_all()
        r2 = self.e.quit_session()
        self.assertTrue(r2.get("ok"), r2)
        self.assertEqual(r2.get("reason"), "达标离场")

    def test_below_target_with_positions_still_allows_quit(self):
        """未达标时弃权不要求先平仓：引擎强制清算后结算。"""
        self.set_cash(self.tgt * 0.8)
        self.e.s["prices"]["AURA/CORE"] = 100.0
        self.assertTrue(self.e.open_position("AURA/CORE", "LONG", 1, 20).get("ok"))
        r = self.e.quit_session()
        self.assertTrue(r.get("ok"), r)
        self.assertEqual(r.get("reason"), "主动弃权（未达标）")
        self.assertEqual(self.e.s["positions"], [])

    def test_exactly_at_target_counts_as_hit(self):
        self.set_cash(self.tgt)
        r = self.e.quit_session()
        self.assertEqual(r.get("reason"), "达标离场")
        self.assertTrue(r.get("hit_target"))


class HitAtTickTest(_Base):
    def test_hit_at_tick_recorded_once(self):
        self.e.s["tick"] = 40
        self.set_cash(self.tgt * 1.1)
        self.e.tick()
        first = self.e.s.get("hit_at_tick")
        self.assertIsNotNone(first)
        # 再跑一 tick 不应覆盖首次达标时刻
        self.e.tick()
        self.assertEqual(self.e.s.get("hit_at_tick"), first)

    def test_giveback_after_hit_is_reported(self):
        """达标后又亏回去：判定仍是未达成，但报告要写明曾达标。"""
        self.set_cash(self.tgt * 1.2)
        self.e.s["hit_at_tick"] = 77
        self.set_cash(self.tgt * 0.7)
        r = self.e.quit_session()
        self.assertFalse(r.get("hit_target"))
        self.assertIn("主动弃权", r.get("reason", ""))
        # 事件流里要有「曾于第 77 tick 达标」的结论
        end_events = [x for x in self.e.s.get("events", []) if x.get("kind") == "end"]
        self.assertTrue(end_events)
        self.assertIn("第 6 分 25 秒", end_events[-1].get("text", ""))


class IdleSkipTest(_Base):
    def test_idle_abort_skipped_after_hit(self):
        """达标后继续持有是规则允许的等待，不该被「无操作」自动收尾杀掉。"""
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
        self.assertFalse(self.e.s.get("finished"), "达标后不应被 idle 收尾")

        # 反证：没有 hit_at_tick（且低于目标）时仍会被收尾
        self.e.s["hit_at_tick"] = None
        self.set_cash(self.tgt * 0.9)
        self.e.tick()
        self.assertTrue(self.e.s.get("finished"))


if __name__ == "__main__":
    unittest.main()
