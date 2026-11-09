# -*- coding: utf-8 -*-
"""无活动自动收尾的回归测试（v1.2.13 起：判定下沉引擎、按 tick 计时）。

这条防线针对的是「人类误点 AI 版的启动脚本」：
对局会正常开始，但没有任何人下单，45 分钟全部空转。

四个方向都必须测到——
  · 真的没人操作时，必须提前结算；
  · 有写操作时，绝不能误杀；
  · 失败请求（参数错误）不能用来无限续命；
  · 只读观察不计入活动，慢思考等待不会被提前结算。

另外一个关键约束：判定必须由引擎自己记账。v1.2.12 把埋点放在 HTTP 路由层，
导致 bench.py 直调引擎的离线基线与真实参赛者受不同规则约束。
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
    """把阈值压到 1 分钟，方便在几个 tick 内跑完判定。"""

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
        eng.roll_stop()          # 定档后才开始计时
        return eng

    def push_idle(self, eng):
        """把「上次动作」推到刚好超过阈值的位置。"""
        eng.s["last_action_tick"] = eng.s["tick"] - T.IDLE_ABORT_TICKS


class TestIdleAbort(_IdleBase):
    def test_idle_abort_triggers(self):
        """连续无操作超过阈值必须自动结算，并把原因写进 last_settle。"""
        eng = self.make()
        self.push_idle(eng)
        eng.tick()
        self.assertTrue(eng.s["finished"])
        self.assertIn(str(T.IDLE_ABORT_MINUTES), eng.s["last_settle"]["reason"])

    def test_write_actions_reset_idle(self):
        """所有改变对局状态的方法都要刷新计时 —— 直调引擎也算（不依赖 HTTP）。"""
        cases = [
            ("open_position", lambda e: e.open_position("AURA/CORE", "LONG", 1, 20)),
            ("borrow", lambda e: e.borrow(100000)),
            ("fast_forward", lambda e: e.fast_forward(180)),
            ("scratch_append", lambda e: e.scratch_append("笔记")),
            ("set_trader", lambda e: e.set_trader("回归测试")),
            ("slot", lambda e: e.slot(10000)),
            ("assist_enable", lambda e: e.assist_enable()),
            ("close_all", lambda e: e.close_all()),
        ]
        for name, call in cases:
            eng = self.make()
            self.push_idle(eng)
            r = call(eng)
            self.assertIsNot(r.get("ok"), False, "%s 调用失败：%s" % (name, r))
            self.assertEqual(eng.s["last_action_tick"], eng.s["tick"],
                             "%s 没有刷新活动计时" % name)
            eng.tick()
            self.assertFalse(eng.s["finished"], "%s 之后仍被误杀" % name)

    def test_failed_request_does_not_reset(self):
        """参数错误的请求不能续命：活动只在成功路径上记账。"""
        eng = self.make()
        self.push_idle(eng)
        r = eng.open_position("NOT_A_PAIR", "LONG", 1, 20)
        self.assertIs(r.get("ok"), False)
        self.assertNotEqual(eng.s["last_action_tick"], eng.s["tick"])
        eng.tick()
        self.assertTrue(eng.s["finished"])

    def test_read_only_does_not_reset(self):
        """只读观察不计入活动：等待与推理是合法策略，不该被砍掉。"""
        eng = self.make()
        before = eng.s["last_action_tick"]
        eng.state()
        eng.rules()
        eng.state()
        self.assertEqual(eng.s["last_action_tick"], before)

    def test_rules_text_comes_from_engine(self):
        """/rules 的文案与判定同源：阈值、活动口径、只读说明缺一不可。"""
        eng = self.make()
        text = json.dumps(eng.rules(), ensure_ascii=False)
        self.assertIn(str(T.IDLE_ABORT_MINUTES), text)
        self.assertIn("只读观察", text)
        self.assertIn("慢思考", text)


class TestIdleDisabled(unittest.TestCase):
    """默认关闭（TM_IDLE_ABORT 未设或为 0）时的行为。"""

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
        self.assertIn("已关闭", text)


if __name__ == "__main__":
    unittest.main()
