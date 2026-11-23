import json
from pathlib import Path
import random
import sys
import tempfile
import unittest
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

import tm_engine as T


class PoolTest(unittest.TestCase):
    def setUp(self):
        home = self.enterContext(tempfile.TemporaryDirectory())
        self.engine = T.Engine(home)

    def set_tasks(self, *keys, tier=0):
        self.engine.reset(count=False, seed=42, roll_index=7)
        self.engine.challenge_decline()
        self.engine.roll_stop()
        tasks = [
            {"key": key, "name": name, "kind": kind, "tier": tier,
             "desc": T._challenge_desc(key, tier), "status": "pending"}
            for key, name, kind in T.CHALLENGE_POOL if key in keys
        ]
        self.engine.s["challenge"].update(stage="on", tasks=tasks, peak_eq=T.STARTER_CASH)
        return {task["key"]: task for task in tasks}

    def test_rules_list_all_unique_functional_entries(self):
        rules = self.engine.rules()
        self.assertEqual(len(T.NEWS_TABLE), 40)
        self.assertEqual(len(rules["随机事件池"]), 40)
        self.assertEqual(len(T.CHALLENGE_POOL), 20)
        self.assertEqual(len(rules["挑战任务池"]), 20)
        self.assertEqual(len({row[0] for row in T.CHALLENGE_POOL}), 20)
        for name, _, kind, params in T.NEWS_TABLE:
            with self.subTest(event=name):
                before = len(self.engine.s["events"])
                self.engine._apply_news(name, kind, params)
                self.assertEqual(len(self.engine.s["events"]), before + 1)
                self.assertIn(name, self.engine.s["events"][-1]["text"])

    def test_wave_draws_distinct_risk_mechanisms(self):
        rows = {row[0]: row for row in T.NEWS_TABLE}
        for seed in range(100):
            with self.subTest(seed=seed):
                self.engine._market_rng = random.Random(seed)
                self.engine.s.update(tick=50, huge_wave_warn_until=50, events=[])
                with patch.object(self.engine, "_apply_news") as apply_news:
                    self.assertTrue(self.engine._roll_huge_wave())
                names = [call.args[0] for call in apply_news.call_args_list]
                self.assertIn(len(names), (3, 4, 5))
                self.assertTrue(set(names).isdisjoint(T.HUGE_WAVE_EXCLUDE_NAMES))
                self.assertTrue(any(rows[name][2] in T.PRICE_NEWS_KINDS for name in names))
                self.assertEqual(len({T._wave_group(rows[name]) for name in names}), len(names))

    def test_depth_event_changes_state_and_slippage_until_expiry(self):
        pair = "AURA/CORE"
        self.engine.s["tick"] = 1
        depth = self.engine.state()["liquidity"][pair]
        slip = self.engine._slip_rate(0, 1_000_000, pair)
        for name, mult in (("做市商撤单", 0.75), ("深度回补", 1.5)):
            row = next(row for row in T.NEWS_TABLE if row[0] == name)
            self.engine._apply_news(name, row[2], row[3])
            self.assertAlmostEqual(self.engine.state()["liquidity"][pair], depth * mult, places=3)
            self.assertAlmostEqual(self.engine._slip_rate(0, 1_000_000, pair), slip / mult)
            self.engine.s["tick"] += 10
            self.engine._expire_mods()
            self.assertEqual(self.engine.state()["liquidity"][pair], depth)

    def test_draw_has_one_result_and_two_distinct_applicable_constraints(self):
        seen = set()
        for seed in range(400):
            self.engine.s.update(seed=seed, target=T.TARGET_EQUITY, assist_on=True)
            self.engine.s["special"]["slot"] = True
            tasks = self.engine._challenge_make()
            self.assertEqual([t["kind"] for t in tasks], ["final", "hold", "hold"])
            self.assertNotEqual(T.CHALLENGE_GROUP[tasks[1]["key"]], T.CHALLENGE_GROUP[tasks[2]["key"]])
            self.assertEqual(self.engine.s["target"],
                             T.TARGET_EQUITY * (2 if tasks[0]["key"] == "double_goal" else 1))
            seen.update(t["key"] for t in tasks)
        self.assertEqual(len(seen), 20)
        self.engine.s["assist_on"] = False
        self.engine.s["special"]["slot"] = False
        for seed in range(100):
            self.engine.s.update(seed=seed, target=T.TARGET_EQUITY)
            picks = {t["key"] for t in self.engine._challenge_make()}
            self.assertTrue(picks.isdisjoint({"no_slot", "no_assist"}))

    def test_immediate_position_and_leverage_violations_persist_after_close(self):
        tasks = self.set_tasks("no_dual", "leverage_cap", "notional_cap", tier=2)
        pair = "AURA/CORE"
        self.assertTrue(self.engine.open_position(pair, "LONG", 1, 10)["ok"])
        self.assertTrue(self.engine.open_position(pair, "LONG", 14, 20)["ok"])
        self.assertTrue(self.engine.open_position(pair, "SHORT", 1, 10)["ok"])
        self.assertTrue(self.engine.close_all()["ok"])
        self.assertEqual({task["status"] for task in tasks.values()}, {"failed"})
        self.assertEqual(self.engine.s["tick"], 0)

    def test_hold_counts_tick_zero_and_only_full_exit_after_last_add(self):
        task = self.set_tasks("hold_long", tier=1)["hold_long"]
        pair = "AURA/CORE"
        self.assertTrue(self.engine.open_position(pair, "LONG", 2, 10)["ok"])
        self.engine.s["tick"] = 5
        self.assertTrue(self.engine.close_position(pair, lots=1)["ok"])
        self.assertEqual(self.engine.state()["challenge"]["hold_hits"], 0)
        self.assertTrue(self.engine.close_position(pair)["ok"])
        self.assertEqual(self.engine.state()["challenge"]["hold_hits"], 1)
        self.assertTrue(self.engine.open_position(pair, "LONG", 1, 10)["ok"])
        self.engine.s["tick"] = 9
        self.assertTrue(self.engine.open_position(pair, "LONG", 1, 10)["ok"])
        self.engine.s["tick"] = 10
        self.assertTrue(self.engine.close_position(pair)["ok"])
        self.assertEqual(task["status"], "pending")
        self.assertTrue(self.engine.open_position(pair, "LONG", 1, 10)["ok"])
        self.engine.s["tick"] = 15
        self.assertTrue(self.engine.close_position(pair)["ok"])
        self.assertEqual(task["status"], "done")

    def test_realized_results_use_voluntary_fills_and_allocate_entry_fee(self):
        tasks = self.set_tasks("bank_profit", "profitable_pairs", "two_sided")
        pair = "AURA/CORE"
        self.assertTrue(self.engine.open_position(pair, "LONG", 2, 10)["ok"])
        pos = self.engine.s["positions"][0]
        entry_fee = pos["fee"]
        self.engine.s["prices"][pair] += 20
        self.assertTrue(self.engine.close_position(pair, lots=1)["ok"])
        rec = self.engine.s["trades"][-1]
        stats = self.engine.s["challenge"]["closed"]
        self.assertAlmostEqual(stats["pairs"][pair], rec["pnl"] - rec["fee"] - entry_fee / 2)
        self.assertEqual(pos["fee"], entry_fee / 2)
        self.assertEqual(tasks["bank_profit"]["status"], "done")
        self.assertEqual(tasks["profitable_pairs"]["status"], "pending")
        pair = "FROST/CORE"
        self.assertTrue(self.engine.open_position(pair, "SHORT", 1, 10)["ok"])
        self.engine.s["prices"][pair] -= 10
        self.assertTrue(self.engine.close_position(pair)["ok"])
        self.assertEqual(tasks["profitable_pairs"]["status"], "done")
        self.assertEqual(tasks["two_sided"]["status"], "done")

    def test_equity_target_and_fee_cap_use_final_accounting(self):
        tasks = self.set_tasks("double_goal", "fee_cap")
        self.engine.s["target"] = 1_000_100
        self.assertTrue(self.engine.open_position("AURA/CORE", "LONG", 1, 10)["ok"])
        self.engine.s["prices"]["AURA/CORE"] = 150.19
        self.engine.s["total_fees"] = 14_990.0
        self.engine._challenge_update()
        self.assertGreater(self.engine.equity(), self.engine.s["target"])
        self.assertEqual(tasks["double_goal"]["status"], "pending")
        self.engine._end_session("时间到")
        self.assertEqual(tasks["double_goal"]["status"], "failed")
        self.assertEqual(tasks["fee_cap"]["status"], "failed")
        report = next((Path(self.engine.home) / "reports" / "JSON Reports").glob("*.json"))
        self.assertEqual(json.loads(report.read_text(encoding="utf-8"))["challenge"]["failed"], 2)
