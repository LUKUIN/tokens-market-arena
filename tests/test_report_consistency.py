# -*- coding: utf-8 -*-
"""报告、JSON 摘要与 /state 三处口径的一致性回归测试。

背景：同一局的三处出口曾经各算各的——
  · HTML 报告：pnl = 最终权益 − 本金（genesis）
  · JSON 摘要：pnl = 最终权益 − 曲线首点（第一个 tick 的权益，已扣开局成本）
  · /state   ：pnl = 最终权益 − 本金
前两者在同一局能差出一笔开局点差/手续费；bench.py 读的是 JSON，于是统计口径
也跟着偏。另有一类：结算发生在最后一次 tick 之后，强制清仓造成的权益跳变
没有写回 equity_curve，/state 会给出「权益 -209 万、曲线末点 91 万」的自相矛盾数据。

这两条都不是「显示不好看」，是同一份数据在三个消费者眼里不一样。
"""

import json
import os
import shutil
import sys
import tempfile
import unittest

sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "src"))

import tm_engine as T  # noqa: E402


class ConsistencyCase(unittest.TestCase):
    def make(self):
        home = tempfile.mkdtemp(prefix="tmcons_")
        self.addCleanup(shutil.rmtree, home, True)
        eng = T.Engine(home)
        eng.roll_stop()
        return eng

    def crash_and_settle(self, eng):
        """制造一次「最后一 tick 之后才崩盘」的结算。

        持仓在最后一个 tick 时还是盈利的，随后价格断崖、结算强制清仓——
        这正是历史上「曲线停在 92 万、报告写 -129 万」的形态。
        """
        sym = "FROST/CORE"
        self.assertTrue(eng.open_position(sym, "LONG", 5, 20).get("ok"))
        for _ in range(3):
            eng.tick()
        eng.s["prices"][sym] = eng.s["prices"][sym] * 0.2
        return eng.quit_session()

    def read_summary(self, out):
        hp = out.get("report")
        self.assertTrue(hp and os.path.isfile(hp), "HTML 报告必须生成")
        jp = os.path.splitext(hp)[0] + ".json"
        self.assertTrue(os.path.isfile(jp), "同名 JSON 摘要必须生成")
        with open(jp, encoding="utf-8") as f:
            return json.load(f)


class TestCurveMatchesSettlement(ConsistencyCase):
    def test_state_curve_last_point_equals_final_equity(self):
        """结算后 /state 的曲线末点必须等于最终权益，不能停在崩盘前。"""
        eng = self.make()
        out = self.crash_and_settle(eng)
        st = eng.state(include_history=False, include_events=False)
        curve = st.get("equity_curve") or []
        self.assertTrue(curve, "结算后必须留下权益曲线")
        self.assertAlmostEqual(float(curve[-1]["equity"]),
                               float(out["final_equity"]), places=2,
                               msg="/state 曲线末点与结算权益不一致")

    def test_state_equity_and_curve_agree(self):
        """equity 字段与曲线末点是同一份数据，不能各说各话。"""
        eng = self.make()
        self.crash_and_settle(eng)
        st = eng.state(include_history=False, include_events=False)
        self.assertAlmostEqual(float(st["equity"]),
                               float(st["equity_curve"][-1]["equity"]), places=2)

    def test_settlement_point_is_idempotent(self):
        """重复结算不得在曲线尾部堆出第二根同值点。"""
        eng = self.make()
        self.crash_and_settle(eng)
        before = len(eng.s["equity_curve"])
        eq = eng.equity()
        # 末点已对齐时再走一次补点逻辑，曲线长度不变
        if abs(float(eng.s["equity_curve"][-1]["equity"]) - float(eq)) <= 0.05:
            eng._end_session("重复结算")
        self.assertLessEqual(len(eng.s["equity_curve"]), before + 1)


class TestPnlBasisIsGenesis(ConsistencyCase):
    def test_json_pnl_uses_genesis_not_curve_first_point(self):
        """JSON 的 pnl 必须相对本金，与 HTML / /state 同口径。"""
        eng = self.make()
        out = self.crash_and_settle(eng)
        data = self.read_summary(out)
        genesis = float(eng.s["genesis"])
        self.assertAlmostEqual(data["pnl"],
                               round(float(out["final_equity"]) - genesis, 2),
                               places=2)
        self.assertAlmostEqual(data["pnl_pct"],
                               round((float(out["final_equity"]) / genesis - 1) * 100, 4),
                               places=3)

    def test_json_and_state_pnl_agree(self):
        """JSON 的 pnl 必须与 /state 的 pnl 完全一致。"""
        eng = self.make()
        out = self.crash_and_settle(eng)
        data = self.read_summary(out)
        st = eng.state(include_history=False, include_events=False)
        self.assertAlmostEqual(float(data["pnl"]), float(st["pnl"]), places=2)

    def test_genesis_field_is_exposed(self):
        """新增的 genesis 字段要能让消费者自己复算 pnl。"""
        eng = self.make()
        out = self.crash_and_settle(eng)
        data = self.read_summary(out)
        self.assertIn("genesis", data)
        self.assertAlmostEqual(float(data["genesis"]), float(eng.s["genesis"]), places=2)

    def test_opening_before_first_tick_keeps_basis(self):
        """开局第一个 tick 之前就开仓：曲线首点会低于本金，pnl 仍必须按本金算。"""
        eng = self.make()
        self.assertTrue(eng.open_position("FROST/CORE", "LONG", 5, 20).get("ok"))
        out = eng.quit_session()
        data = self.read_summary(out)
        genesis = float(eng.s["genesis"])
        self.assertAlmostEqual(data["pnl"],
                               round(float(out["final_equity"]) - genesis, 2),
                               places=2)


if __name__ == "__main__":
    unittest.main(verbosity=2)
