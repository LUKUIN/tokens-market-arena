#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Paired multi-round benchmark: run a fixed number of matches per seed and
report comparable statistics.

Single-match variance is huge (historical samples run from +106% to -229%), so one match
says nothing about a model. This script turns "same scenarios, same round count" into one command:

    python bench.py run --seeds 1,2,3 --policy noop
    python bench.py run --seeds 1-5 --policy probe
    python bench.py summary --dir src/data/reports

run      play one full match per seed (ticks are advanced in-process: no HTTP, no wall-clock
         waiting) and drop the machine-readable summary into reports/*.json.
summary  scan every *.json in a directory and print mean / median / quantiles / settlement errors.

Note: these policies are headless baselines that verify the engine behaves consistently under a
fixed seed. They do not represent any model. Real agents go through HTTP; this script only
orchestrates and aggregates.
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
    """Do nothing: the baseline for settlement, ledger and seed reproduction."""
    return None


def _policy_probe(eng, rng, tick):
    """Act every 24 ticks: close an open position, otherwise open one at random.

    The point is not profit: it creates paths that carry positions, costs and the
    possibility of a blow-up, so differences between seeds become visible.
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
    """Play one match and return its summary dict, or None on failure."""
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
            print("  seed %d tick %d policy error: %s" % (seed, tick, exc), file=sys.stderr)
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
    # Offline evaluation disables the idle abort by default: the ticks below
    # complete a whole match in a few hundred milliseconds, so a tick-based
    # idle decision would truncate the baseline at 12 minutes and make it
    # incomparable with a real HTTP match. Pass --idle-abort N to test it.
    T.IDLE_ABORT_MINUTES = max(0, int(args.idle_abort))
    T.IDLE_ABORT_TICKS = (T.IDLE_ABORT_MINUTES * 60) // T.TICK_SECONDS
    outdir = args.out or tempfile.mkdtemp(prefix="tmbench_")
    os.makedirs(outdir, exist_ok=True)
    seeds = _parse_seeds(args.seeds)
    if not seeds:
        print("no seeds given", file=sys.stderr)
        return 2
    print("Paired benchmark: %d seed(s), policy %s, output %s" % (len(seeds), args.policy, outdir))
    rows = []
    roll_index = getattr(args, "roll_index", None)
    for i, seed in enumerate(seeds, 1):
        row = run_one(seed, args.policy, outdir, roll_index)
        if row is None:
            print("  [%d/%d] seed %-6d produced no summary" % (i, len(seeds), seed))
            continue
        rows.append(row)
        print("  [%d/%d] seed %-6d equity %12.2f  pnl %8.2f%%  mdd %6.2f%%  %s" % (
            i, len(seeds), seed, row.get("final_equity", 0.0), row.get("pnl_pct", 0.0),
            row.get("max_drawdown_pct", 0.0),
            "settlement error" if not row.get("settled", True) else "ok"))
    _print_stats(rows)
    if args.json:
        with open(args.json, "w", encoding="utf-8") as f:
            json.dump(rows, f, ensure_ascii=False, indent=2)
        print("\nDetails written to %s" % args.json)
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
        print("\nNo samples to summarise.")
        return
    pnl = [float(r.get("pnl_pct") or 0.0) for r in rows]
    mdd = [float(r.get("max_drawdown_pct") or 0.0) for r in rows]
    n = len(rows)
    hits = sum(1 for r in rows if r.get("hit_target"))
    blown = sum(1 for r in rows if not r.get("settled", True))
    audited = sum(1 for r in rows if not (r.get("audit") or []))
    print("\n%d match(es)" % n)
    print("  pnl%%     mean %8.2f   median %8.2f   stdev %8.2f" % (
        statistics.fmean(pnl), statistics.median(pnl),
        statistics.pstdev(pnl) if n > 1 else 0.0))
    print("           P10 %8.2f   P90 %8.2f   best %8.2f   worst %8.2f" % (
        _quantile(pnl, 0.10), _quantile(pnl, 0.90), max(pnl), min(pnl)))
    print("  mdd%%     median %8.2f   worst %8.2f" % (
        statistics.median(mdd), max(mdd)))
    print("  hit target %d/%d   settlement errors %d/%d   ledger audit clean %d/%d" % (
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
            print("skipping %s: %s" % (name, exc), file=sys.stderr)
    _print_stats(rows)
    return 0


def main(argv=None):
    ap = argparse.ArgumentParser(description="TokensMarket paired multi-round benchmark")
    sub = ap.add_subparsers(dest="cmd", required=True)

    p_run = sub.add_parser("run", help="play one match per seed")
    p_run.add_argument("--seeds", required=True, help="e.g. 1,2,3 or 1-5")
    p_run.add_argument("--idle-abort", type=int, default=0,
                       help="idle-abort minutes; default 0 (off) so evaluation stays comparable")
    p_run.add_argument("--roll-index", type=int, default=None,
                       help="pin the difficulty slot, 0-24 (= gap + liq*5); unset means every match draws its own")
    p_run.add_argument("--policy", default="noop", choices=sorted(POLICIES),
                       help="headless baseline policy (default noop)")
    p_run.add_argument("--out", default="", help="output directory (default: temp dir)")
    p_run.add_argument("--json", default="", help="also write the details as JSON")
    p_run.set_defaults(func=cmd_run)

    p_sum = sub.add_parser("summary", help="summarise existing JSON summaries")
    p_sum.add_argument("--dir", default=os.path.join("src", "data", "reports"))
    p_sum.set_defaults(func=cmd_summary)

    args = ap.parse_args(argv)
    return args.func(args)


if __name__ == "__main__":
    sys.exit(main())
