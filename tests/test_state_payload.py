# -*- coding: utf-8 -*-
"""观众席轮询所需的数据量上限，以及 fastforward 不饿死读者的回归测试。

背景：观众席每 300ms 拉一次 /state。
  · 旧版把 price_history（每品种最多 2000 点）和 equity_curve（2000 点）整段下发，
    体积随对局推进线性增长，解析与渲染开销跟着涨；
  · 旧版在 return 里两次调用 _metrics()，每次 /state 白算两遍 MDD/Sharpe；
  · 旧版 fast_forward 整段持 LOCK，一次推进 60 tick 期间所有读取被阻塞。
三者叠加的表现就是观众席周期性显示「服务无响应」，而服务本身一直活着。

这里只锁住两个可测的契约：导出上限，以及快进期间读者不被饿死。
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
        """/state 只下发尾部若干点；内部完整曲线必须保留，报告还要用。"""
        self.e.s["equity_curve"] = self.long_curve(1500)
        st = self.e.state()
        self.assertLessEqual(len(st["equity_curve"]), T.STATE_CURVE_POINTS)
        self.assertEqual(len(self.e.s["equity_curve"]), 1500, "内部曲线不能被截断")

    def test_price_history_export_is_capped(self):
        """每个品种的迷你走势只下发尾部，不能整段 2000 点往外发。"""
        self.e.s["price_history"]["AURA/CORE"] = [100.0 + i * 0.01 for i in range(1500)]
        st = self.e.state()
        self.assertLessEqual(len(st["price_history"]["AURA/CORE"]), T.STATE_HISTORY_POINTS)
        self.assertEqual(len(self.e.s["price_history"]["AURA/CORE"]), 1500)

    def test_history_off_still_empty(self):
        """?history=0 的语义不能被改动：仍然返回空。"""
        st = self.e.state(include_history=False, include_curve=False)
        self.assertEqual(st["price_history"], {})
        self.assertEqual(st["equity_curve"], [])

    def test_metrics_computed_once_per_state(self):
        """/state 里 MDD/Sharpe 只能算一次——重复算两遍是纯浪费 CPU。"""
        calls = {"n": 0}
        orig = self.e._metrics

        def counting(*a, **kw):
            calls["n"] += 1
            return orig(*a, **kw)

        self.e._metrics = counting
        self.e.s["equity_curve"] = self.long_curve(400)
        self.e.state()
        self.assertEqual(calls["n"], 1, "state() 调用 _metrics 的次数应为 1，实际 %d" % calls["n"])


class TestFastForwardYieldsLock(_Base):
    def test_fast_forward_releases_lock_between_ticks(self):
        """结构断言：快进循环必须逐 tick 取锁，而不是整段 with LOCK 包住。

        行为级计时测试在 CI 上不可靠——60 tick 只要 20-40 ms，抢锁线程根本
        抢不到几次（实测 CI 上是 2-3 次，本机 17 次），会制造假失败。
        这里直接钉住代码形状：循环体内出现 with LOCK 且循环体尾部释放。
        """
        import inspect
        src = inspect.getsource(T.Engine.fast_forward)
        self.assertIn("for _ in range(n):", src, "快进循环结构变了，这个断言需要同步更新")
        loop = src.split("for _ in range(n):", 1)[1]
        head = loop[:240]
        self.assertIn("with LOCK:", head,
                      "快进循环体没有单独取锁：整段持锁会把读者饿死")
        self.assertIn("time.sleep(0)", loop,
                      "快进循环没有让出 GIL，HTTP 线程没有插队机会")


if __name__ == "__main__":
    unittest.main(verbosity=2)
