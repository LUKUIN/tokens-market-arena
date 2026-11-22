import os
import sys
import tempfile
import unittest
from unittest.mock import Mock, patch

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "src"))

import tm_engine
import tm_watch


class TestCloseSelected(unittest.TestCase):
    def test_tkinter_closes_only_the_selected_direction(self):
        with tempfile.TemporaryDirectory() as home:
            engine = tm_engine.Engine(home)
            engine.reset(count=False, seed=7, roll_index=12)
            engine.challenge_decline()
            engine.roll_stop()
            pair = next(iter(tm_engine.PAIRS))
            self.assertTrue(engine.open_position(pair, "LONG", 1, 20)["ok"])
            self.assertTrue(engine.open_position(pair, "SHORT", 2, 20)["ok"])

            window = tm_watch.Watch.__new__(tm_watch.Watch)
            window._tp_guard = Mock(return_value=True)
            window._tp_tree = Mock()
            window._tp_tree.selection.return_value = (f"{pair}|LONG",)
            window._tp_say = Mock()

            def close(path, payload):
                self.assertEqual(path, "/close")
                return engine.close_position(**payload)

            with patch.object(tm_watch, "post", side_effect=close):
                window._tp_do_close()

            positions = engine.s["positions"]
            self.assertEqual([(position["side"], position["lots"]) for position in positions],
                             [("SHORT", 2)])
