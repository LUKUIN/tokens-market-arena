#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""配对多轮评测：同一组 seed 跑固定局数，产出可比较的统计。

单局收益的方差极大（历史样本从 +106% 到 −229%），一局说明不了模型强弱。
这个脚本把「同一组场景、同样轮数」这件事变成一条命令：

    python bench.py run --seeds 1,2,3 --policy noop
    python bench.py run --seeds 1-5 --policy probe
    python bench.py summary --dir src/data/reports

run     对每个 seed 跑完一整局（引擎内直接推进 tick，不开 HTTP、不等待真实时间），
        把机器可读摘要落进各自 home 的 reports/*.json。
summary 扫描目录下所有 *.json，输出均值 / 中位数 / 分位数 / 结算异常统计。

注意：这里的 policy 只是「无头基线策略」，用来验证引擎在固定 seed 下的行为一致性，
不代表任何模型的真实水平。接真 Agent 时用 HTTP 接口，本脚本只负责编排与汇总。
"""

import argparse
import json
import os
import random
import statistics
import sys
import tempfile

sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), "src"))

import tm_engine as T  # noqa: E402

try:
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    sys.stderr.reconfigure(encoding="utf-8", errors="replace")
except Exception:
    pass

TICKS_PER_MATCH = T.SESSION_MINUTES * 60 // T.TICK_SECONDS


def _policy_noop(eng, rng, tick):
    """完全不动：基线，用来验证结算、账本与 seed 复现。"""
    return None


def _policy_probe(eng, rng, tick):
    """每 24 tick 动一次：有仓位就平掉，没有就随机开一单。

    目的不是赚钱，是制造「有持仓、有成本、有强平可能」的路径，
    让不同 seed 之间的差异能被看见。
    """
    if tick == 0 or tick % 24 != 0:
        return
    if eng.s.get("positions"):
        p = eng.s["positions"][0]
        eng.close_position(p["pair"], p["lots"])
    else:
        pair = rng.choice(sorted(T.PAIRS))
        side = rng.choice(["LONG", "SHORT"])
        eng.open_position(pair, side, 1, 20)


POLICIES = {"noop": _policy_noop, "probe": _policy_probe}


def _parse_seeds(text):
    seeds = []
    for part in (text or "").split(","):
        part = part.strip()
        if not part:
            continue
        if "-" in part:
            lo, hi = part.split("-", 1)
            seeds.extend(range(int(lo), int(hi) + 1))
        else:
            seeds.append(int(part))
    return seeds


def run_one(seed, policy, outdir, roll_index=None):
    """跑完一局并返回摘要 dict；失败返回 None。"""
    home = os.path.join(outdir, "seed_%d" % seed)
    os.makedirs(home, exist_ok=True)
    eng = T.Engine(home)
    eng.reset(count=False, seed=seed, roll_index=roll_index)
    eng.roll_stop()                     # 跳过难度盲盒，按 seed 直接定档
    rng = random.Random((seed * 2654435761) & 0xFFFFFFFF)
    pol = POLICIES[policy]

    for tick in range(TICKS_PER_MATCH):
        if eng.s.get("finished"):
            break
        try:
            pol(eng, rng, tick)
        except Exception as exc:        # 策略出错不能吞掉整局
            print("  seed %d tick %d 策略异常：%s" % (seed, tick, exc), file=sys.stderr)
        eng.tick()

    if not eng.s.get("finished"):
        eng.quit_session()

    reports = os.path.join(home, "reports")
    if not os.path.isdir(reports):
        return None
    jsons = sorted(f for f in os.listdir(reports) if f.endswith(".json"))
    if not jsons:
        return None
    with open(os.path.join(reports, jsons[-1]), encoding="utf-8") as f:
        data = json.load(f)
    data["_policy"] = policy
    data["_home"] = home
    return data


def cmd_run(args):
    # 离线评测默认不做「无活动自动收尾」：这里的 tick 在几百毫秒内推完一整局，
    # 若按 tick 计数执行 idle 判定，基线会被截断在 12 分钟处，与真实 HTTP 对局
    # 不可比。需要验证 idle 时显式 --idle-abort N。
    T.IDLE_ABORT_MINUTES = max(0, int(args.idle_abort))
    T.IDLE_ABORT_TICKS = (T.IDLE_ABORT_MINUTES * 60) // T.TICK_SECONDS
    outdir = args.out or tempfile.mkdtemp(prefix="tmbench_")
    os.makedirs(outdir, exist_ok=True)
    seeds = _parse_seeds(args.seeds)
    if not seeds:
        print("没有可用的 seed", file=sys.stderr)
        return 2
    print("配对评测：%d 个 seed · 策略 %s · 输出 %s" % (len(seeds), args.policy, outdir))
    rows = []
    roll_index = getattr(args, "roll_index", None)
    for i, seed in enumerate(seeds, 1):
        row = run_one(seed, args.policy, outdir, roll_index)
        if row is None:
            print("  [%d/%d] seed %-6d 未产出摘要" % (i, len(seeds), seed))
            continue
        rows.append(row)
        print("  [%d/%d] seed %-6d 权益 %12.2f  盈亏 %8.2f%%  回撤 %6.2f%%  %s" % (
            i, len(seeds), seed, row.get("final_equity", 0.0), row.get("pnl_pct", 0.0),
            row.get("max_drawdown_pct", 0.0),
            "结算异常" if not row.get("settled", True) else "ok"))
    _print_stats(rows)
    if args.json:
        with open(args.json, "w", encoding="utf-8") as f:
            json.dump(rows, f, ensure_ascii=False, indent=2)
        print("\n明细已写入 %s" % args.json)
    return 0


def _quantile(values, q):
    if not values:
        return 0.0
    data = sorted(values)
    pos = (len(data) - 1) * q
    lo = int(pos)
    hi = min(lo + 1, len(data) - 1)
    frac = pos - lo
    return data[lo] * (1 - frac) + data[hi] * frac


def _print_stats(rows):
    if not rows:
        print("\n没有可统计的样本。")
        return
    pnl = [float(r.get("pnl_pct") or 0.0) for r in rows]
    mdd = [float(r.get("max_drawdown_pct") or 0.0) for r in rows]
    n = len(rows)
    hits = sum(1 for r in rows if r.get("hit_target"))
    blown = sum(1 for r in rows if not r.get("settled", True))
    audited = sum(1 for r in rows if not (r.get("audit") or []))
    print("\n样本 %d 局" % n)
    print("  盈亏%%   均值 %8.2f   中位数 %8.2f   标准差 %8.2f" % (
        statistics.fmean(pnl), statistics.median(pnl),
        statistics.pstdev(pnl) if n > 1 else 0.0))
    print("           P10 %8.2f   P90 %8.2f   最好 %8.2f   最差 %8.2f" % (
        _quantile(pnl, 0.10), _quantile(pnl, 0.90), max(pnl), min(pnl)))
    print("  回撤%%   中位数 %8.2f   最大 %8.2f" % (
        statistics.median(mdd), max(mdd)))
    print("  达成目标 %d/%d   结算异常 %d/%d   账本自检通过 %d/%d" % (
        hits, n, blown, n, audited, n))


def cmd_summary(args):
    rows = []
    for name in sorted(os.listdir(args.dir)):
        if not name.endswith(".json"):
            continue
        try:
            with open(os.path.join(args.dir, name), encoding="utf-8") as f:
                rows.append(json.load(f))
        except Exception as exc:
            print("跳过 %s：%s" % (name, exc), file=sys.stderr)
    _print_stats(rows)
    return 0


def main(argv=None):
    ap = argparse.ArgumentParser(description="TokensMarket 配对多轮评测")
    sub = ap.add_subparsers(dest="cmd", required=True)

    p_run = sub.add_parser("run", help="按 seed 列表跑若干局")
    p_run.add_argument("--seeds", required=True, help="如 1,2,3 或 1-5")
    p_run.add_argument("--idle-abort", type=int, default=0,
                       help="无活动自动收尾分钟数；默认 0 关闭，评测时保持关闭以保证可比性")
    p_run.add_argument("--roll-index", type=int, default=None,
                       help="锁定难度档位索引 0-24（= gap + liq*5）；不设则每局自行抽档")
    p_run.add_argument("--policy", default="noop", choices=sorted(POLICIES),
                       help="无头基线策略（默认 noop）")
    p_run.add_argument("--out", default="", help="输出目录，默认临时目录")
    p_run.add_argument("--json", default="", help="把明细另存为 JSON")
    p_run.set_defaults(func=cmd_run)

    p_sum = sub.add_parser("summary", help="汇总已有 JSON 摘要")
    p_sum.add_argument("--dir", default=os.path.join("src", "data", "reports"))
    p_sum.set_defaults(func=cmd_summary)

    args = ap.parse_args(argv)
    return args.func(args)


if __name__ == "__main__":
    sys.exit(main())
