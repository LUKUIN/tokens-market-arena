# -*- coding: utf-8 -*-
"""v1.2.22 回归：本机轮询链路的编码与代理健壮性。

背景（现场证据）：
    17:29 那一局退出时 run.err.log 留下
        UnicodeDecodeError: 'utf-8' codec can't decode byte 0xbb in position 2
    run.log 紧接着
        收尾清理失败：'NoneType' object has no attribute 'splitlines'
    两者是同一条链：subprocess(text=True) 在 UTF-8 模式下解 GBK 的 netstat 输出，
    reader 线程崩 → stdout=None → splitlines() 崩。

这些用例只断言「结构与解码行为」，不做计时型并发断言
（v1.2.21 的教训：CI 的 Windows runner 上计时断言会假失败）。
"""
import os
import sys
import unittest

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)
sys.path.insert(0, os.path.join(ROOT, "src"))


def _read(rel):
    with open(os.path.join(ROOT, rel), encoding="utf-8") as f:
        return f.read()


class TestConsoleDecode(unittest.TestCase):
    def setUp(self):
        import run
        self.run_mod = run

    def test_gbk_bytes(self):
        # netstat 的「活动连接」在中文 Windows 上是 GBK 字节
        raw = "活动连接".encode("gbk")
        self.assertEqual(self.run_mod._decode_bytes(raw), "活动连接")

    def test_utf8_bytes(self):
        raw = "活动连接".encode("utf-8")
        self.assertEqual(self.run_mod._decode_bytes(raw), "活动连接")

    def test_empty_and_none_safe(self):
        self.assertEqual(self.run_mod._decode_bytes(b""), "")
        self.assertEqual(self.run_mod._decode_bytes(None), "")

    def test_listening_pids_never_raises(self):
        # 端口随便给一个：无论有没有监听，都必须是 list，不能抛异常
        self.assertIsInstance(self.run_mod._listening_pids(65533), list)


class TestLocalProxyBypass(unittest.TestCase):
    def test_opener_has_no_proxy_handler(self):
        import run
        names = [type(h).__name__ for h in run._LOCAL_OPENER.handlers]
        self.assertNotIn("ProxyHandler", names, "本机请求必须直连，不能被系统代理劫持")

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
