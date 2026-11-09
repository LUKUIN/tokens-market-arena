# -*- coding: utf-8 -*-
"""无活动自动收尾的回归测试。

这条防线针对的是「人类误点 AI 版的启动脚本」：
对局会正常开始，但没有任何人下单，45 分钟全部空转。
所以两个方向都必须测到——
  · 真的没人操作时，必须提前结算；
  · 有人操作时，绝不能误杀。
"""

import os
import shutil
import sys
import tempfile
import time
import unittest

sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "src"))

import tm_engine as T  # noqa: E402


class IdleAbortCase(unittest.TestCase):
    def make(self):
        home = tempfile.mkdtemp(prefix="tmidle_")
        self.addCleanup(shutil.rmtree, home, True)
        eng = T.Engine(home)
        eng.roll_stop()
        return eng


class TestIdleAbort(IdleAbortCase):
    def test_idle_abort_triggers(self):
        """连续无操作超过阈值必须自动结算，并把原因写进 last_settle。"""
        if T.IDLE_ABORT_MINUTES <= 0:
            self.skipTest("TM_IDLE_ABORT=0，功能已关闭")
        eng = self.make()
        eng.s["last_action_at"] = time.time() - (T.IDLE_ABORT_MINUTES * 60 + 1)
        eng.tick()
        self.assertTrue(eng.s["finished"])
        self.assertIn(str(T.IDLE_ABORT_MINUTES), eng.s["last_settle"]["reason"])

    def test_action_resets_idle(self):
        """note_action 必须重置计时，活跃参赛者不能被误杀。"""
        if T.IDLE_ABORT_MINUTES <= 0:
            self.skipTest("TM_IDLE_ABORT=0，功能已关闭")
        eng = self.make()
        eng.s["last_action_at"] = time.time() - (T.IDLE_ABORT_MINUTES * 60 + 1)
        eng.note_action()
        eng.tick()
        self.assertFalse(eng.s["finished"])

    def test_rules_mentions_idle(self):
        """/rules 必须把这条规则写出来，否则 Agent 无从得知。"""
        eng = self.make()
        rules = eng.rules()
        text = str(rules)
        self.assertIn(str(T.IDLE_ABORT_MINUTES), text)


if __name__ == "__main__":
    unittest.main()
