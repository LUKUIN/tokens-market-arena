import concurrent.futures
import json
from pathlib import Path
import sys
import tempfile
import unittest
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

import tm_engine as market
import tm_report_store as reports


class TestStorageResilience(unittest.TestCase):
    def setUp(self):
        self.home = self.enterContext(tempfile.TemporaryDirectory())
        self.engine = market.Engine(self.home, simulated=True)
        self.engine.challenge_decline()
        self.engine.roll_stop()
        self.session_id = self.engine.s["session_id"]
        self.path = Path(self.engine.path)

    def open(self, lots=1, request_id="order", **kwargs):
        return self.engine.open_position("AURA/CORE", "LONG", lots, 20, request_id=request_id, **kwargs)

    def test_same_request_is_serialized_and_replays_after_restart(self):
        with concurrent.futures.ThreadPoolExecutor(2) as pool:
            first, second = list(pool.map(lambda _: self.open(), range(2)))
        self.assertEqual([r.get("replayed", False) for r in (first, second)].count(True), 1)
        self.engine = market.Engine(self.home, simulated=True)
        self.assertTrue(self.open()["replayed"])
        self.assertEqual(self.engine.s["order_count"], 1)
        self.assertEqual(self.open(lots=2)["code"], "idempotency_conflict")
        self.assertEqual(self.open(expected_session="previous")["code"], "session_mismatch")

    def test_failed_trade_restores_rng_state_and_cannot_leak_to_next_save(self):
        previous = self.path.read_bytes()
        rng = self.engine._player_rng.getstate()
        real_write = market.atomic_write

        def fail_primary(path, content):
            if Path(path) == self.path:
                raise OSError("disk unavailable")
            return real_write(path, content)

        with patch.object(market, "atomic_write", side_effect=fail_primary):
            with self.assertRaises(OSError):
                self.engine.borrow(1000, request_id="loan")
        self.assertEqual(self.engine._player_rng.getstate(), rng)
        self.assertEqual(self.engine.s["loan"]["balance"], 0)
        self.assertEqual(self.path.read_bytes(), previous)
        self.assertTrue(self.engine.borrow(1000, request_id="loan")["ok"])
        self.assertEqual(json.loads(self.path.read_bytes())["loan"]["balance"], 1000)

    def test_corrupt_save_uses_verified_backup_and_preserves_bytes(self):
        self.assertTrue(self.open()["ok"])
        damaged = b"{broken"
        self.path.write_bytes(damaged)
        resumed = market.Engine(self.home, simulated=True)
        self.assertEqual(resumed.s["session_id"], self.session_id)
        self.assertTrue(resumed.s["tampered"])
        self.assertTrue(resumed.state()["storage_recovery"])
        recovery_files = list((Path(self.home) / "reports" / "Recovery").glob("*.json"))
        self.assertEqual([f.read_bytes() for f in recovery_files], [damaged])

    def test_unrecoverable_save_is_never_overwritten(self):
        bad = b"{broken"
        self.path.write_bytes(bad)
        Path(str(self.path) + ".previous").write_bytes(bad)
        with self.assertRaises(market.SessionRecoveryError):
            market.Engine(self.home, simulated=True)
        self.assertEqual(self.path.read_bytes(), bad)

    def test_reports_export_independently_and_can_be_retried_after_new_match(self):
        def fail_json(path, content):
            if Path(path).suffix == ".json":
                raise OSError("JSON reports unavailable")
            return market.atomic_write(path, content)

        with patch.object(reports, "atomic_write", side_effect=fail_json):
            out = self.engine.quit_session()
        self.assertTrue(out["settled"])
        self.assertTrue(out["report_status"]["html"]["ok"])
        self.assertFalse(out["report_status"]["json"]["ok"])
        self.assertTrue(Path(out["report"]).is_file())
        next_match = market.Engine(self.home, simulated=True)
        self.assertNotEqual(next_match.s["session_id"], self.session_id)
        recovered = market.Engine.reexport_report(self.home, self.session_id)
        self.assertEqual(out["report"], recovered["html"]["path"])
        summary = json.loads(Path(recovered["json"]["path"]).read_bytes())
        self.assertEqual(summary["session_id"], self.session_id)
        self.assertEqual(summary["final_equity"], out["final_equity"])

    def test_verified_settlement_is_authoritative_if_session_save_fails(self):
        real_write = market.atomic_write

        def fail_primary(path, content):
            if Path(path) == self.path:
                raise OSError("active snapshot unavailable")
            return real_write(path, content)

        with patch.object(market, "atomic_write", side_effect=fail_primary):
            out = self.engine.quit_session()
        self.assertIn("save_warning", out)
        self.assertTrue(out["settled"])
        self.assertFalse(json.loads(self.path.read_bytes())["finished"])
        reader = market.Engine(self.home, readonly=True, simulated=True)
        self.assertTrue(reader.s["finished"])
        self.assertEqual(reader.s["session_id"], self.session_id)

    def test_archive_failure_leaves_match_open_and_allows_settlement_retry(self):
        real_write = market.atomic_write

        def fail_archive(path, content):
            if "Settlement Snapshots" in Path(path).parts:
                raise OSError("archive unavailable")
            return real_write(path, content)

        with patch.object(market, "atomic_write", side_effect=fail_archive):
            with self.assertRaises(OSError):
                self.engine.quit_session()
        self.assertFalse(self.engine.s["finished"])
        self.assertFalse(json.loads(self.path.read_bytes())["finished"])
        self.assertTrue(self.engine.quit_session()["settled"])


if __name__ == "__main__":
    unittest.main()
