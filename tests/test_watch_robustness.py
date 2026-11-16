# -*- coding: utf-8 -*-
"""v1.2.22 regression: encoding and proxy robustness of the local polling path.

Evidence from the field (17:29 run):
    run.err.log: UnicodeDecodeError: 'utf-8' codec can't decode byte 0xbb in position 2
    run.log:     Failed to clean up: 'NoneType' object has no attribute 'splitlines'
Same chain: subprocess(text=True) decodes GBK netstat output as UTF-8 under PYTHONUTF8=1,
the reader thread dies, stdout becomes None, splitlines() dies.

These cases assert structure and decoding behaviour only - no wall-clock concurrency
assertions (the v1.2.21 lesson: timing assertions fail falsely on CI Windows runners).
"""
import os
import sys
import unittest

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)
sys.path.insert(0, os.path.join(ROOT, "src"))

IS_RUNNABLE = sys.version_info[:2] == (3, 14)


def _read(rel):
    with open(os.path.join(ROOT, rel), encoding="utf-8") as f:
        return f.read()


@unittest.skipUnless(IS_RUNNABLE, "run.py 的版本守卫只允许 Python 3.14 导入，其余版本 import 即退出 2")
class TestConsoleDecode(unittest.TestCase):
    def setUp(self):
        import run
        self.run_mod = run

    def test_gbk_bytes(self):
        raw = "活动连接".encode("gbk")
        self.assertEqual(self.run_mod._decode_bytes(raw), "活动连接")

    def test_utf8_bytes(self):
        raw = "活动连接".encode("utf-8")
        self.assertEqual(self.run_mod._decode_bytes(raw), "活动连接")

    def test_empty_and_none_safe(self):
        self.assertEqual(self.run_mod._decode_bytes(b""), "")
        self.assertEqual(self.run_mod._decode_bytes(None), "")

    def test_listening_pids_never_raises(self):
        self.assertIsInstance(self.run_mod._listening_pids(65533), list)


@unittest.skipUnless(IS_RUNNABLE, "run.py 的版本守卫只允许 Python 3.14 导入，其余版本 import 即退出 2")
class TestLocalProxyBypass(unittest.TestCase):
    def test_opener_has_no_proxy_handler(self):
        import run
        names = [type(h).__name__ for h in run._LOCAL_OPENER.handlers]
        self.assertNotIn("ProxyHandler", names, "local requests must not go through a proxy")

    def test_watch_client_uses_local_opener(self):
        src = _read(os.path.join("src", "tm_watch_ai.py"))
        self.assertIn("_OPENER.open(API + path", src)
        self.assertIn("_OPENER.open(req", src)
        self.assertNotIn("urllib.request.urlopen(", src)


class TestTailSpeedFix(unittest.TestCase):
    def test_auto_tick_reads_dict_key(self):
        src = _read(os.path.join("src", "tm_api.py"))
        self.assertIn('.get("hit_at_tick")', src)
        self.assertNotIn('getattr(ENGINE.s, "hit_at_tick"', src)


if __name__ == "__main__":
    unittest.main()
