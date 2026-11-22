# -*- coding: utf-8 -*-
"""本机轮询与对局清理的回归测试。"""
import os
from pathlib import Path
import shutil
import subprocess
import sys
import tempfile
import unittest

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)
sys.path.insert(0, os.path.join(ROOT, "src"))

IS_RUNNABLE = sys.version_info[:2] == (3, 14)


def _read(rel):
    with open(os.path.join(ROOT, rel), encoding="utf-8") as f:
        return f.read()


@unittest.skipUnless(os.name == "nt", "Windows PowerShell required")
class TestCleanup(unittest.TestCase):
    def test_preserves_live_match_and_reports(self):
        with tempfile.TemporaryDirectory() as tmp:
            checkout = Path(tmp)
            tools = checkout / "tools"
            tools.mkdir()
            script = tools / "deep-clean.ps1"
            shutil.copyfile(Path(ROOT) / "tools" / script.name, script)
            (checkout / "run.py").touch()
            data = checkout / "src" / "data"
            reports = data / "reports"
            reports.mkdir(parents=True)
            (reports / "history.html").touch()
            save = data / "session.json"
            save.touch()
            marker = data / ".running"
            marker.write_text(f"session-id\t{os.getpid()}\n")
            command = ["powershell.exe", "-NoProfile", "-ExecutionPolicy", "Bypass",
                       "-File", str(script)]

            result = subprocess.run(command, capture_output=True, timeout=20)
            self.assertNotEqual(result.returncode, 0, result.stdout)
            self.assertTrue(save.is_file())
            marker.unlink()

            result = subprocess.run(command, capture_output=True, timeout=20)
            self.assertEqual(result.returncode, 0, result.stderr)
            self.assertFalse(save.exists())
            self.assertTrue((reports / "history.html").is_file())


@unittest.skipUnless(IS_RUNNABLE, "run.py 的版本守卫只允许 Python 3.14 导入，其余版本 import 即退出 2")
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
