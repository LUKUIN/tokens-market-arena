# -*- coding: utf-8 -*-
"""账本不变量审计、事件序号、报告摘要与配对评测的回归测试。

这里最重要的一条纪律是：**审计本身必须能被证伪**。
只测「干净账本不报错」等于没测——那样即使 _audit_ledger 永远返回 []
也会全绿。所以每个检测项都配一条「故意改坏账本、必须报出来」的用例。
"""

import json
import os
import shutil
import sys
import tempfile
import unittest

sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "src"))

import tm_engine as T  # noqa: E402


class AuditCase(unittest.TestCase):
    def make(self):
        home = tempfile.mkdtemp(prefix="tmaudit_")
        self.addCleanup(shutil.rmtree, home, True)
        eng = T.Engine(home)
        eng.roll_stop()
        return eng


class TestLedgerAudit(AuditCase):
    def test_clean_ledger_reports_nothing(self):
        """干净账本必须零 issue。"""
        eng = self.make()
        eng.open_position("FROST/CORE", "LONG", 5, 20)
        for _ in range(3):
            eng.tick()
        eng.close_position("FROST/CORE", None)
        self.assertEqual(eng._audit_ledger(), [])

    def test_detects_fee_mismatch(self):
        """累计手续费被改坏时必须报出来（证伪检查本身有效）。"""
        eng = self.make()
        eng.open_position("FROST/CORE", "LONG", 5, 20)
        eng.close_position("FROST/CORE", None)
        eng.s["total_fees"] = float(eng.s.get("total_fees") or 0.0) + 100.0
        issues = eng._audit_ledger()
        self.assertTrue(any("手续费" in x for x in issues), issues)

    def test_detects_loan_inconsistency(self):
        """贷款余额与 借入-已还+利息 对不上时必须报出来。"""
        eng = self.make()
        eng.borrow(200000)
        eng.s["loan"]["balance"] = float(eng.s["loan"]["balance"]) + 1.0
        issues = eng._audit_ledger()
        self.assertTrue(any("贷款" in x for x in issues), issues)

    def test_detects_illegal_position(self):
        """方向非法、手数为零的持仓必须被识别。"""
        eng = self.make()
        eng.s["positions"].append({"pair": "LUMEN/CORE", "side": "SIDEWAYS",
                                   "lots": 0, "entry": 1.0, "leverage": 20})
        issues = eng._audit_ledger()
        self.assertTrue(any("方向非法" in x for x in issues), issues)
        self.assertTrue(any("手数非法" in x for x in issues), issues)

    def test_state_exposes_audit(self):
        eng = self.make()
        st = eng.state()
        self.assertIn("audit", st)
        self.assertEqual(st["audit"], [])

    def test_settlement_warnings_include_audit(self):
        """结算时若账目被改坏，warnings 里必须出现审计结论。"""
        eng = self.make()
        eng.s["total_fees"] = float(eng.s.get("total_fees") or 0.0) + 50.0
        out = eng.quit_session()
        self.assertFalse(out["settled"])
        self.assertTrue(any("手续费" in w for w in out["warnings"]), out["warnings"])


class TestEventSequence(AuditCase):
    def test_seq_is_monotonic(self):
        eng = self.make()
        for _ in range(5):
            eng.tick()
        seqs = [e["seq"] for e in eng.s["events"]]
        self.assertTrue(seqs)
        self.assertEqual(seqs, sorted(seqs))
        self.assertEqual(len(set(seqs)), len(seqs), "seq 必须唯一")

    def test_events_carry_session_id(self):
        eng = self.make()
        eng.tick()
        self.assertTrue(eng.s["events"])
        for e in eng.s["events"]:
            self.assertEqual(e["session"], eng.s.get("session_id", ""))


class TestReportSummary(AuditCase):
    def test_json_summary_written_next_to_html(self):
        """每份 HTML 报告旁边必须有一份同名的机器可读 JSON。"""
        eng = self.make()
        eng.open_position("FROST/CORE", "LONG", 2, 20)
        eng.close_position("FROST/CORE", None)
        out = eng.quit_session()
        hp = out["report"]
        self.assertTrue(hp and os.path.isfile(hp), hp)
        jp = os.path.splitext(hp)[0] + ".json"
        self.assertTrue(os.path.isfile(jp), jp)
        with open(jp, encoding="utf-8") as f:
            data = json.load(f)
        for key in ("engine_version", "protocol_version", "seed", "final_equity",
                    "pnl_pct", "settled", "audit"):
            self.assertIn(key, data)
        self.assertEqual(data["audit"], [])


class TestSeededReset(AuditCase):
    def test_reset_accepts_explicit_seed(self):
        """显式 seed 必须真的驱动随机流，而不是只写进字段。"""
        eng_a = self.make()
        eng_a.reset(count=False, seed=123456)
        eng_a.roll_stop()
        a = eng_a.state()["prices"]

        eng_b = self.make()
        eng_b.reset(count=False, seed=123456)
        eng_b.roll_stop()
        b = eng_b.state()["prices"]

        self.assertEqual(eng_a.s["seed"], 123456)
        self.assertEqual(a, b)

    def test_different_seed_changes_market(self):
        """不同 seed 必须走出不同行情。

        注意：开局那一瞬的报价是常量表，seed 只影响之后的随机游走，
        所以要推进几个 tick 再比较，否则这个断言本身是错的。
        """
        eng_a = self.make()
        eng_a.reset(count=False, seed=1)
        eng_a.roll_stop()
        eng_b = self.make()
        eng_b.reset(count=False, seed=2)
        eng_b.roll_stop()
        for _ in range(3):
            eng_a.tick()
            eng_b.tick()
        self.assertNotEqual(eng_a.state()["prices"], eng_b.state()["prices"])


class TestProtocolVersion(AuditCase):
    def test_protocol_version_is_exposed(self):
        self.assertIsInstance(T.PROTOCOL_VERSION, int)
        self.assertGreaterEqual(T.PROTOCOL_VERSION, 1)
        self.assertTrue(hasattr(T, "ENGINE_VERSION"))


class TestScratchpadAndTrader(AuditCase):
    def test_scratchpad_clear(self):
        """POST /scratchpad {"clear": true} 必须真的清空。"""
        eng = self.make()
        eng.scratch_append("第一条")
        eng.scratch_append("第二条")
        self.assertEqual(len(eng.scratch_read()), 2)
        out = eng.scratch_clear()
        self.assertTrue(out["ok"])
        self.assertEqual(eng.scratch_read(), [])

    def test_trader_name_sanitized(self):
        """参赛标识只保留白名单字符，HTML 标签会被剔除。"""
        eng = self.make()
        out = eng.set_trader('<img src=x onerror=alert(1)>测')
        self.assertTrue(out["ok"])
        self.assertNotIn("<", out["trader"])
        self.assertNotIn(">", out["trader"])
        self.assertIn("测", out["trader"])

    def test_report_escapes_event_text(self):
        """事件文本进报告前必须被转义，不能把 <script> 当标签渲染。"""
        eng = self.make()
        eng.set_trader("<b>x</b>")
        eng._event("<script>alert(1)</script>", "info")
        out = eng._end_session("测试转义")
        hp = out.get("report")
        self.assertTrue(hp and os.path.isfile(hp), hp)
        with open(hp, encoding="utf-8") as f:
            doc = f.read()
        self.assertNotIn("<script>alert(1)</script>", doc)
        self.assertIn("&lt;script&gt;", doc)


if __name__ == "__main__":
    unittest.main(verbosity=2)
