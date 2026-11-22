import tempfile
import unittest
from unittest.mock import patch

import bench


class TestBenchmark(unittest.TestCase):
    def test_baseline_completes_a_match_and_records_market_movement(self):
        with tempfile.TemporaryDirectory() as outdir, patch.object(bench.T, "IDLE_ABORT_TICKS", 0):
            report = bench.run_one(7, "noop", outdir)
            self.assertEqual(report["tick"], bench.TICKS_PER_MATCH)
            self.assertTrue(report["settled"])

            path = bench._record_path(7, ticks=2)
            self.assertEqual(len(path), 2)
            self.assertNotEqual(path[0], path[1])
