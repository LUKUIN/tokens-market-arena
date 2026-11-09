#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Paired multi-round benchmark: run a fixed number of matches per seed and
report comparable statistics.

Single-match variance is huge (historical samples run from +106% to -229%), so one match
says nothing about a model. This script turns "same scenarios, same round count" into one command:

    python bench.py run --seeds 1,2,3 --policy noop
    python bench.py run --seeds 1-5 --policy probe
    python bench.py run --seeds 1-5 --policy oracle
    TM_ORACLE_ACC=0.6 python bench.py run --seeds 1-5 --policy oracle
    python bench.py summary --dir src/data/reports

run      play one full match per seed (ticks are advanced in-process: no HTTP, no wall-clock
         waiting) and drop the machine-readable summary into reports/*.json.
summary  scan every *.json in a directory and print mean / median / quantiles / settlement errors.

Policies are headless baselines, not model results:
  noop    never trade - settlement and ledger baseline
  probe   open/close one random order every 24 ticks - paths with positions and costs
  oracle  perfect foresight (replays once to record the path, then trades the next 24 ticks).
          A mechanical upper bound, not an attainable target; TM_ORACLE_ACC injects an error
          rate (1.0 perfect / 0.5 pure random) to get an accuracy -> goal-rate curve.

Real agents go through HTTP; this script only orchestrates and aggregates.
"""

import argparse
import json
import os
import random
import shutil
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


ORACLE_ACC = float(os.environ.get("TM_ORACLE_ACC") or 1.0)


def _record_path(seed, roll_index=None, ticks=None):
    """Replay an empty match and record per-tick prices, so oracle can "see the future".

    With a fixed seed the price path does not depend on whether we hold positions
    (verified tick-for-tick), so this empty run is exactly the path of the real one.
    """
    ticks = ticks or TICKS_PER_MATCH
    home = tempfile.mkdtemp(prefix="tm_oracle_")
    try:
        eng = T.Engine(home)
        eng.reset(count=False, seed=seed, roll_index=roll_index)
        eng.roll_stop()
        path = []
        for _ in range(ticks):
            eng.tick()
            path.append(dict(eng.s["prices"]))
        return path
    finally:
        shutil.rmtree(home, True)


def _policy_oracle(eng, rng, tick):
    """Perfect foresight: pick direction and size from the recorded path.

    Every 24 ticks: take the pair with the largest absolute move over the next 24 ticks
    and open 3x equity notional (20x leverage) in that direction. Not strict optimal
    control, but enough to answer "where is the mechanical ceiling".
    """
    path = getattr(eng, "_oracle_path", None)
    if not path or tick >= len(path):
        return
    if tick % 24 != 0:
        return
    for p in list(eng.s.get("positions") or []):
        eng.close_position(p["pair"], p["lots"])
    i = min(tick, len(path) - 1)
    j = min(tick + 24, len(path) - 1)
    if j <= i:
        return
    best = None
    for pair in sorted(T.PAIRS):
        p0, p1 = path[i][pair], path[j][pair]
        ret = (p1 - p0) / p0
        if best is None or abs(ret) > abs(best[1]):
            best = (pair, ret, p1)
    if not best or abs(best[1]) < 0.002:
        return
    pair, ret, price = best
    if ORACLE_ACC < 1.0 and rng.random() > ORACLE_ACC:
        ret = -ret
    notional = eng.equity() * 3.0
    lots = max(1, int(notional / (1000.0 * price)))
    eng.open_position(pair, "LONG" if ret > 0 else "SHORT", lots, 20)


POLICIES = {"noop": _policy_noop, "probe": _policy_probe, "oracle": _policy_oracle}


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
    eng.roll_stop()                     # skip the difficulty blind box, lock by seed
    if policy == "oracle":
        # The recording run calls random.seed(seed) and advances 540 ticks, so the global
        # RNG is left ahead of the start; reset again or the live path will not match.
        eng._oracle_path = _record_path(seed, roll_index)
        eng.reset(count=False, seed=seed, roll_index=roll_index)
        eng.roll_stop()
    # Offline runs never pass through the launcher, so TM_TRADER is empty and the match is
    # flagged unnamed, which would force hit_target to False. A benchmark wants engine
    # behaviour, not match eligibility, so clear it explicitly.
    eng.s["unnamed"] = False
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
        # Not quit_session: above the target it returns a valid-exit report, but what a
        # benchmark wants is the result of a full 540-tick match. Go straight to settlement.
        eng._end_session("benchmark complete")

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
