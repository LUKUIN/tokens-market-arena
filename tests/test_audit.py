# -*- coding: utf-8 -*-
"""Regression tests for the ledger audit, event sequence, report summary and seeded reset.

The discipline that matters most here: **the audit itself must be falsifiable**.
Testing only "a clean ledger reports nothing" tests nothing -- _audit_ledger could always
return [] and stay green. Every detector therefore also gets a "deliberately corrupt the
ledger, the audit must complain" case.
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
        """A clean ledger must produce zero issues."""
        eng = self.make()
        eng.open_position("FROST/CORE", "LONG", 5, 20)
        for _ in range(3):
            eng.tick()
        eng.close_position("FROST/CORE", None)
        self.assertEqual(eng._audit_ledger(), [])

    def test_detects_fee_mismatch(self):
        """A corrupted fee total must be reported (proves the check is falsifiable)."""
        eng = self.make()
        eng.open_position("FROST/CORE", "LONG", 5, 20)
        eng.close_position("FROST/CORE", None)
        eng.s["total_fees"] = float(eng.s.get("total_fees") or 0.0) + 100.0
        issues = eng._audit_ledger()
        self.assertTrue(any("手续费" in x for x in issues), issues)

    def test_detects_loan_inconsistency(self):
        """A loan balance that does not equal borrowed - repaid + interest must be reported."""
        eng = self.make()
        eng.borrow(200000)
        eng.s["loan"]["balance"] = float(eng.s["loan"]["balance"]) + 1.0
        issues = eng._audit_ledger()
        self.assertTrue(any("贷款" in x for x in issues), issues)

    def test_detects_illegal_position(self):
        """Illegal side and zero lots must both be detected."""
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
        """If the ledger is corrupted, settlement warnings must carry the audit verdict."""
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
        self.assertEqual(len(set(seqs)), len(seqs), "seq must be unique")

    def test_events_carry_session_id(self):
        eng = self.make()
        eng.tick()
        self.assertTrue(eng.s["events"])
        for e in eng.s["events"]:
            self.assertEqual(e["session"], eng.s.get("session_id", ""))


class TestReportSummary(AuditCase):
    def test_json_summary_written_next_to_html(self):
        """Every HTML report must be accompanied by a same-named machine-readable JSON."""
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
        """An explicit seed must actually drive the RNG, not just be recorded."""
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
        """Different seeds must produce different markets.

        Note: the opening quotes are a constant table; the seed only affects the random
        walk afterwards, so a few ticks must be advanced before comparing.
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
        """POST /scratchpad {"clear": true} must actually wipe the pad."""
        eng = self.make()
        eng.scratch_append("first")
        eng.scratch_append("second")
        self.assertEqual(len(eng.scratch_read()), 2)
        out = eng.scratch_clear()
        self.assertTrue(out["ok"])
        self.assertEqual(eng.scratch_read(), [])

    def test_trader_name_sanitized(self):
        """Trader label keeps only allow-listed characters; HTML tags are stripped."""
        eng = self.make()
        out = eng.set_trader('<img src=x onerror=alert(1)>En')
        self.assertTrue(out["ok"])
        self.assertNotIn("<", out["trader"])
        self.assertNotIn(">", out["trader"])

    def test_report_escapes_event_text(self):
        """Event text must be escaped before it reaches the report."""
        eng = self.make()
        eng.set_trader("<b>x</b>")
        eng._event("<script>alert(1)</script>", "info")
        out = eng._end_session("escape test")
        hp = out.get("report")
        self.assertTrue(hp and os.path.isfile(hp), hp)
        with open(hp, encoding="utf-8") as f:
            doc = f.read()
        self.assertNotIn("<script>alert(1)</script>", doc)
        self.assertIn("&lt;script&gt;", doc)


if __name__ == "__main__":
    unittest.main(verbosity=2)
