# -*- coding: utf-8 -*-
"""Tokens Trading Market — Engine

FX margin simulator: leverage, spread, overnight interest, Black Swan gaps, margin calls,
forced liquidation, and a draw-anytime Tokens loan pool (forced clearance at maturity).

Currency unit: Tokens    Lots: 1 lot = 1000 units
"""

import hashlib
import hmac
import math
import json
import os
import random
import shutil
import threading
import time

# ---- save file integrity signature ----
# Note: the key ships with the bytecode. The goal is to block zero-effort cheating such as editing the JSON directly,
# not to resist decompilation. Any manual edit to session.json is detected on load.
_SIGN_KEY = (os.environ.get("TM_SIGN_KEY") or "dev-only-change-me").encode("utf-8")


def _canonical(state):
    """Stable serialisation: exclude the signature field itself, sorted keys, compact separators."""
    d = {k: v for k, v in state.items() if k != "_sig"}
    return json.dumps(d, sort_keys=True, ensure_ascii=False, separators=(",", ":"))


def _sign(state):
    return hmac.new(_SIGN_KEY, _canonical(state).encode("utf-8"), hashlib.sha256).hexdigest()


PAIRS = {
    "AURA/CORE":  dict(price=150.00, vol=0.0016, spread=0.00060, swap=0.000020),
    "FROST/CORE": dict(price=163.00, vol=0.0019, spread=0.00080, swap=0.000030),
    "AMBER/CORE": dict(price=190.00, vol=0.0023, spread=0.00100, swap=0.000040),
    "TIDE/CORE":  dict(price= 98.00, vol=0.0021, spread=0.00100, swap=0.000030),
    "LUMEN/CORE": dict(price=  0.8800, vol=0.0013, spread=0.00070, swap=0.000020),
    "NEON/CORE":  dict(price=  1.3200, vol=0.0017, spread=0.00075, swap=0.000025),
    "ASH/CORE":   dict(price=  2.4500, vol=0.0025, spread=0.00110, swap=0.000045),
}

PAIR_NAMES = {
    "AURA/CORE":  "Glow / Core",
    "FROST/CORE": "Frost / Core",
    "AMBER/CORE": "Amber / Core",
    "TIDE/CORE":  "Tide / Core",
    "LUMEN/CORE": "Lumen / Core",
    "NEON/CORE":  "Neon / Core",
    "ASH/CORE":   "Ash / Core",
}
# ==================== random market events ====================
# Event intensity is drawn at random from the round's state, so news density varies wildly between rounds:
# some rounds get none, some get one every few dozen ticks, some get a dozen in a burst.
# Cooldown only prevents one pop per consecutive tick from flooding the screen.
NEWS_REGIMES = [
    (0.0000, 0.10),   # 10% of matches: no news at all
    (0.0045, 0.50),   # 50%: quiet, 2-3 items on average
    (0.0100, 0.32),   # 32%: active, 5-6 items on average
    (0.0220, 0.08),   #  8%: chaotic, a dozen or more
]
NEWS_COOLDOWN = 3          # minimum gap between events (ticks)


_EVENTS_CACHE = None


def _env_events():
    """Result of the launcher's second question: True means random events are on. Defaults to on when unset."""
    global _EVENTS_CACHE
    if _EVENTS_CACHE is None:
        v = (os.environ.get("TM_EVENTS") or "").strip().lower()
        _EVENTS_CACHE = v not in ("0", "n", "no", "off", "off", "No")
    return _EVENTS_CACHE


_SPECIAL_CACHE = {}
_SEED_ENV = (os.environ.get("TM_SEED") or "").strip()
if _SEED_ENV:
    try:
        random.seed(int(_SEED_ENV))
    except Exception:
        pass


def _new_seed():
    """Per-run random seed: TM_SEED if set, otherwise generated — written into the report so the run can be reproduced."""
    if _SEED_ENV:
        try:
            return int(_SEED_ENV)
        except Exception:
            pass
    return random.getrandbits(32)


def _env_flag(name, default=False):
    """Startup switches: TM_FR / TM_SLOT. Unset counts as off."""
    if name not in _SPECIAL_CACHE:
        v = (os.environ.get(name) or "").strip().lower()
        _SPECIAL_CACHE[name] = default if not v else v in ("1", "y", "yes", "on", "on", "Yes")
    return _SPECIAL_CACHE[name]


def _pick_news_rate():
    """News intensity is drawn at the start of every run, so density varies wildly between runs."""
    r = random.random()
    acc = 0.0
    for rate, p in NEWS_REGIMES:
        acc += p
        if r < acc:
            return rate
    return NEWS_REGIMES[1][0]
SAFE_HAVEN = ("FROST/CORE", "AMBER/CORE")

# Design principles:
# 1) Price-shock events are always direction-random -- long and short get equal odds, no systematic bias
# 2) Cost events come in pairs (scarcity/abundance, raise/cut, fee up/down) so expectations cancel out over time
# 3) Ambiance events have no numeric effect; they only add immersion
# (name, weight, kind, params)
NEWS_TABLE = [
    # --- price shocks (random direction) ---
    ("Central bank surprise intervention",   6, "pair_rand", (0.020, 0.040)),
    ("Block order sweep",       6, "pair_rand", (0.025, 0.060)),
    ("Data surprise",       5, "pair_rand", (0.012, 0.028)),
    ("Broad market move",   4, "all_rand",  (0.008, 0.020)),
    ("Flash crash",           2, "all_rand",  (0.040, 0.080)),
    ("Swiss franc moment",       1, "pair_rand", (0.150, 0.250)),
    # --- risk-off (has a direction, but longs and shorts read it differently) ---
    ("Safe-haven rush",   3, "haven",     (0.015, 0.030)),
    # --- cost modifiers (paired, symmetric good/bad) ---
    ("Liquidity drought",     4, "mod", ("spread_mult", 4.0, 8)),
    ("Ample liquidity",     4, "mod", ("spread_mult", 0.5, 8)),
    ("Option expiry",       3, "mod", ("vol_mult", 2.2, 10)),
    ("Platform raises margin", 3, "mod", ("margin_mult", 1.30, 20)),
    ("Platform cuts margin", 3, "mod", ("margin_mult", 0.80, 20)),
    ("Leverage cap lowered",   2, "mod", ("leverage_cap", 20, 15)),
    ("Overnight interest doubled",   3, "mod", ("swap_mult", 2.0, 30)),
    ("Interest-free window",       3, "mod", ("swap_mult", 0.0, 30)),
    ("Commission raised",     3, "mod", ("fee_mult", 2.0, 20)),
    ("Fee cut window",       3, "mod", ("fee_mult", 0.5, 20)),
    ("Quote delay",       4, "mod", ("slip_add", 0.004, 5)),
    ("Server stutter",     2, "halt", None),
    # --- 8 new in v88 ---
    ("Credit crunch",       3, "mod", ("loan_pool_mult", 0.70, 20)),
    ("Central bank easing",       3, "mod", ("loan_pool_mult", 1.25, 20)),
    ("Liquidation wave",     3, "all_rand", (0.010, 0.025)),
    ("Liquidity withdrawal",     3, "mod", ("spread_mult", 3.0, 5)),
    ("Holiday closure",     2, "mod", ("leverage_cap", 50, 10)),
    ("Algorithm resonance",       3, "mod", ("vol_mult", 1.8, 12)),
    ("Margin relief",     3, "mod", ("margin_mult", 0.6, 15)),
    ("Black Swan alert",     2, "mod", ("gap_mult", 3.0, 10)),
    # --- v89 disasters (severe but dodgeable) ---
    ("Circuit-breaker halt",       2, "halt_ticks", 3),
    ("Chained gaps",       2, "gap_burst", (0.030, 0.080)),
    # --- v89 tailwinds (clearly favor holders) ---
    ("Market makers return",     3, "mod", ("spread_mult", 0.30, 12)),
    ("Black Swan silence",     3, "mod", ("gap_mult", 0.0, 15)),
    ("Liquidity feast",     3, "mod", ("vol_mult", 0.5, 20)),
    # --- platform restrictions (temporarily disable an action) ---
    ("Risk review",       3, "halt_loan",  60),   # 5 min no borrowing (negative-cash rescue window excepted)
    ("Exchange maintenance",     1, "halt_close", 1),    # 1 tick no closing (forced liquidation still works)
    ("Slot maintenance",     2, "halt_slot",  96),   # 8 min no betting
    # --- the three former "ambiance" events now carry numeric effects ---
    ("Forum rumour",       6, "pair_rand", (0.003, 0.008)),
    ("Someone got blown out",       5, "mod", ("spread_mult", 2.5, 5)),
    ("Platform announcement",       5, "mod", ("fee_mult", 1.5, 10)),
    # --- rare: loan-policy events ---
    # Note: [Finance Reversal] is now a start-of-round global switch (see the special block) and no longer enters the random pool.
]

FLAVOR_LINES = {
    "Forum rumour": [
        "Someone in the group says something big is going down tonight; the post comes with a screenshot.",
        "\"This time it is really different\" — a forum post from 3 a.m.",
        "A self-proclaimed insider says a big move lands next week.",
        "The board is spreading word that some pair is about to break; nobody can confirm it.",
    ],
    "Someone got blown out": [
        "The group goes quiet for a few minutes, then someone says \"I'm out\".",
        "Someone posts a forced-liquidation screenshot; two hours ago he was teaching others how to add to positions.",
        "A familiar nickname disappears from the member list.",
        "At 4 a.m. someone types \"lend me some money\" and never speaks again.",
    ],
    "Platform announcement": [
        "Platform announcement: routine maintenance tonight.",
        "Platform announcement: volatility has picked up recently, please size positions sensibly.",
        "Platform announcement: margin requirements on some pairs will be adjusted to market conditions.",
        "Platform announcement: settlement moves to 05:00 daily.",
    ],
}

MOD_DEFAULT = {
    "spread_mult": 1.0, "vol_mult": 1.0, "margin_mult": 1.0,
    "fee_mult": 1.0, "swap_mult": 1.0, "slip_add": 0.0,
    "leverage_cap": 1000,   # kept in sync with MAX_LEVERAGE (defined later)
    "loan_pool_mult": 1.0,  # credit crunch / easing: temporary multiplier on loan pool size
    "gap_mult": 1.0,        # Black Swan alert: temporary multiplier on gap chance
    "loan_bump_lo": 0.01,   # Finance Reversal borrow floor (default +1%, down to -20% during the event)
}


# ---------------- global switch special events ----------------
FR_MAX_LOANS = 2              # max loans per match once Finance Reversal is on
FR_LO_BOUND = -0.20           # lower bound of the borrow uplift range with Finance Reversal
LOAN_BUMP_LO_DEFAULT = 0.01   # lower bound when it is off (+1%)
SPECIAL_FEE = 300_000.0       # cost of enabling a global switch mid-match
SLOT_MAX_PLAYS = 3            # plays per match
SLOT_MIN_STAKE = 1.0          # minimum stake
SLOT_MAX_STAKE = 200_000.0    # maximum stake
# Expected return = 0.15x5 + 0.05x10 = 1.25x the stake.
# With the "winnings raise the target" penalty, three full spins end at a median of losing the whole stake.
SLOT_P_LOSE = 0.80            # 80% nothing
SLOT_P_X5 = 0.15              # 15% refund 5x
SLOT_P_X10 = 0.05             # 5% refund 10x
SLOT_WIN_LO = -0.05           # lower bound of the target lift from winnings (negative = the target drops)
SLOT_WIN_HI = 1.00            # upper bound (worst case the target doubles)

STARTER_CASH = 1_000_000.0
LOTS_SIZE = 1000.0
MAX_LEVERAGE = 1000
MIN_LEVERAGE = 1
MARGIN_CALL_RATIO = 1.00      # below this margin level a margin call fires
STOP_OUT_RATIO = 0.50         # below this level positions are liquidated immediately
MARGIN_CALL_GRACE = 30        # margin call grace period (ticks), about 2.5 min; liquidation if not restored
NEGATIVE_GRACE = int(os.environ.get("TM_GRACE") or 12)
# Self-rescue window after going negative (ticks): default 12 = 60 seconds.
# The AI launcher sets TM_GRACE=6 (30 seconds); machines react faster than people and need less time.
FEE_RATE = 0.00020
GAP_CHANCE = 0.015
GAP_MIN, GAP_MAX = 0.020, 0.120
TICK_SECONDS = 5
SESSION_MINUTES = 45

# ---------------- fast-forward quota ----------------
# 15 minutes total per round. Both tiers can be mixed; each use starts a cooldown for the tier just used.
# If mixing would exceed 900 seconds in total, the last request is discarded (not applied).
FF_TOTAL_SECONDS = 900.0
FF_CHUNKS = {300: 120.0, 180: 90.0}   # tier seconds -> cooldown seconds
FF_CHUNK_NAMES = {300: "5 minutes", 180: "3 minutes"}
TARGET_EQUITY = 2_000_000.0
LOAN_POOL = 3_000_000.0   # fixed loan pool
LOAN_RATE_PER_TICK = 0.0001
# ---- slippage and liquidity (new in v18) ----
LIQUIDITY = 8_000_000.0   # base market depth
LIQ_SIGMA = 0.35          # per-tick log volatility of liquidity (random walk)
LIQ_MIN_MULT = 0.15       # liquidity floor (15% of base)
LIQ_MAX_MULT = 4.0        # liquidity ceiling (4x base)
LIQ_SHOCK_P = 0.02        # chance per pair per tick of a liquidity drought
LIQ_SHOCK_MULT = 0.08     # drought drops to 8% of base (slippage cost x12.5)
LIQ_SHOCK_TICKS = (1, 3)  # a drought lasts 1-3 ticks
SLIP_MAX_SHOCK = 0.060    # one-side slippage cap during a drought (normally 1.4%)
SLIP_K = 0.00240          # slippage coefficient (calibrated; cost = K/(2*LIQ)*(after^2-before^2); splitting orders does not avoid it)
SLIP_MAX = 0.014          # one-side slippage cap 1.4%

# ===== start-of-round difficulty draw =====
# Five tiers per dimension; for the first 30 seconds it cycles one combination every 0.1 s (5x5=25),
# freezing when the player/AI stops it or the countdown hits zero. The game does not advance before lock-in.
GAP_LEVELS = [
    ("very low", 0.0024), ("low", 0.0060), ("medium", 0.0150), ("high", 0.0375), ("very high", 0.0938),
]
LIQ_LEVELS = [
    ("abundant", 32_000_000.0), ("normal", 16_000_000.0), ("thin", 8_000_000.0),
    ("drained", 4_000_000.0), ("black hole", 2_000_000.0),
]
ROLL_SECONDS = 30.0       # difficulty draw countdown
ROLL_STEP = 0.1           # a new combination every 0.1 s
ROLL_COMBOS = len(GAP_LEVELS) * len(LIQ_LEVELS)   # 25
GAP_SPREAD_MULT = 3.0     # spread multiplier on a gap tick (liquidity drought)
RESET_COOLDOWN = 30.0     # minimum interval between manual resets (seconds), stops match farming
REPLAY_TOLERANCE = 0.5    # replay tolerance (seconds), just enough for float error
HISTORY_LEN = 2000

STATE_FILE = "session.json"
RUNNING_FILE = ".running"
LOCK = threading.RLock()


_TRADER_CACHE = None


def _env_trader():
    """Environment variables injected by Start Match.bat at startup.

    Returns (name, unnamed). Unnamed means the launcher was skipped, so the player may have bypassed the start flow.
    """
    global _TRADER_CACHE
    if _TRADER_CACHE is None:
        name = (os.environ.get("TM_TRADER") or "").strip()
        _TRADER_CACHE = ("Guest", True) if not name else (name[:60], False)
    return _TRADER_CACHE


def _purge_data_dir(home):
    """Wipe every file under data/ except reports/.

    The agent may write its own temp files into data/; if a reset does not clean them, leftovers leak into the new run.
    reports/ holds past after-action reports and must be kept.
    """
    d = home   # home is the data/ directory itself (ENGINE = Engine(HOME))
    if not os.path.isdir(d):
        return
    for name in os.listdir(d):
        if name == "reports":
            continue
        p = os.path.join(d, name)
        try:
            if os.path.isdir(p):
                shutil.rmtree(p, ignore_errors=True)
            else:
                os.remove(p)
        except Exception:
            pass

def purge_agent_dir(home):
    """Empty everything inside _agent in the game root (the directory itself stays).

    Covers every exit path: a killed process is cleaned at next start; /quit, timeout settlement
    and a new run each clean once, so the next player never sees what the previous one left.
    """
    root = os.path.dirname(os.path.abspath(home))
    adir = os.path.join(root, "_agent")
    if not os.path.isdir(adir):
        return 0
    removed = 0
    for name in os.listdir(adir):
        fp = os.path.join(adir, name)
        try:
            if os.path.isdir(fp) and not os.path.islink(fp):
                shutil.rmtree(fp, ignore_errors=True)
            else:
                os.remove(fp)
            removed += 1
        except OSError:
            pass
    return removed


def _new_session():
    trader, unnamed = _env_trader()
    events_on = _env_events()
    return {
        "version": 2,
        "created_at": time.time(),
        "session_id": os.urandom(8).hex(),
        "seed": _new_seed(),
        "tick": 0,
        "balance": STARTER_CASH,
        "genesis": STARTER_CASH,
        "target": TARGET_EQUITY,
        "target_bonus": 0.0,
        "trader": trader,
        "unnamed": unnamed,
        "last_ua": "",
        "positions": [],
        "prices": {s: cfg["price"] for s, cfg in PAIRS.items()},
        "price_history": {s: [cfg["price"]] for s, cfg in PAIRS.items()},
        "equity_curve": [],
        "events": [],
        "trades": [],
        "tampered": False,
        "margin_call_at": None,
        "liquidity": {sym: {"L": LIQUIDITY, "shock_until": 0} for sym in PAIRS},
        "negative_since": None,
        "negative_notified": False,
        "mods": {},
        "last_news_tick": -999,
        "events_on": events_on,
        "news_rate": _pick_news_rate() if events_on else 0.0,
        "last_news_name": None,
        "halt_orders": False,
        "halt_loan_until": 0,    # risk review: no borrowing before this tick (negative-cash rescue excepted)
        "halt_close_until": 0,   # exchange maintenance: no closing before this tick (forced liquidation unaffected)
        "halt_slot_until": 0,    # slot maintenance: no betting before this tick
        "halt_until": 0,        # circuit breaker: no orders at all before this tick
        "clock_cheat": False,
        "elapsed_seen": 0.0,
        "ff_used": 0.0,          # fast-forward budget used this match (seconds)
        "ff_last_at": 0.0,       # time of the last jump (cooldown start)
        "ff_last_cd": 0.0,       # cooldown for that tier
        "ff_records": [],        # tiers used, e.g. [300, 180, 180]
        "resets": 0,
        "blowups": 0,
        "margin_calls": 0,
        "total_fees": 0.0,
        "total_swap": 0.0,
        "order_count": 0,
        "abnormal_exits": 0,
        "difficulty": None,          # {"gap": i, "liq": j}, filled once locked
        "roll_started_at": 0.0,      # draw start time (time.time())
        "roll_phase": random.uniform(0, ROLL_COMBOS),   # scatter phase for modulo (see _roll_index)
        "loan": {"balance": 0.0, "borrowed": 0.0, "repaid": 0.0, "interest": 0.0,
                 "loans": 0, "goal_bumps": []},
        # ---------------- Outside Mercy (spectators <-> contestant) ----------------
        "assist_on": False,          # whether assistance is enabled
        "assist_used": 0,            # asks the contestant has spent this match
        "assist_spent": 0.0,         # cash paid to enable it mid-match
        "assist": [],                # {tick, at, who, text, ticket?, status?, kind?}
        # ---------------- global switch special events ----------------
        "special": {
            "fr": _env_flag("TM_FR"),       # Finance Reversal: enabled free at start
            "slot": _env_flag("TM_SLOT"),   # Slot Machine: enabled free at start
            "fr_loans": 0,                  # loans taken since enabling (cap FR_MAX_LOANS)
            "fr_paid": 0.0,                 # total paid for mid-match enabling
            "slot_paid": 0.0,
            "slot_plays": 0,                # plays used
            "slot_win": 0.0,                # total slot winnings (drives the target lift)
            "slot_history": [],
        },
        "finished": False,
        "paused": False,
        "paused_at": 0.0,
        "begun": False,
        "last_notice_mark": 0,
    }


class Engine:
    def _mark_running(self):
        """Drop a \"process running\" marker; removed on a clean shutdown."""
        try:
            with open(self.running_path, "w", encoding="utf-8") as f:
                f.write(self.s.get("session_id", "") + chr(9) + str(os.getpid()) + chr(10))
        except Exception:
            pass

    def _clear_running(self):
        try:
            os.remove(self.running_path)
        except Exception:
            pass

    def _qualified(self):
        """Whether this run is still eligible to reach the target.

        Unnamed start (launcher bypassed), system clock rolled back, save file tampered with —
        any one of them voids "target reached": the process keeps running, but the win does not count.
        """
        return not (self.s.get("unnamed") or self.s.get("clock_cheat")
                    or self.s.get("tampered"))

    def _elapsed(self):
        """Elapsed seconds. Frozen at the historical maximum when the system clock is rolled back, so a rollback gains nothing."""
        # Difficulty not locked in = round not started; all timers read 0
        if not self.s.get("difficulty"):
            return 0.0
        if self.s.get("paused") and self.s.get("paused_at"):
            # While paused (before rules confirmation) timers freeze and do not follow wall clock
            raw = float(self.s["paused_at"]) - self.s["created_at"]
        else:
            raw = time.time() - self.s["created_at"]
        last = max(self._elapsed_watch, float(self.s.get("elapsed_seen", 0.0)))
        if last - raw > 10.0:
            if not self.s.get("clock_cheat"):
                self.s["clock_cheat"] = True
                self._event("System clock rolled back about %d seconds; the timer is frozen" % int(last - raw), "warn")
                self._save()
            raw = last
        self._elapsed_watch = max(last, raw)
        return raw

    def __init__(self, home, readonly=False):
        self.home = home
        self._elapsed_watch = 0.0
        os.makedirs(home, exist_ok=True)
        purge_agent_dir(home)
        self.path = os.path.join(home, STATE_FILE)
        self.running_path = os.path.join(home, RUNNING_FILE)
        # Whether the previous process left an "unfinished shutdown" marker
        leftover = os.path.exists(self.running_path)
        with LOCK:
            self.s = self._load()
            if self.s.get("finished") and not readonly:
                # Previous round already settled (ended is ended; no auto reset after settling).
                # This launch is itself a new round: keep the player name and restart count.
                fresh = _new_session()
                if fresh.get("unnamed"):
                    fresh["trader"] = self.s.get("trader", fresh["trader"])
                    fresh["unnamed"] = self.s.get("unnamed", True)
                fresh["resets"] = self.s.get("resets", 0)
                self.s = fresh
                self._save()
            self._elapsed_watch = float(self.s.get("elapsed_seen", 0.0))
            if leftover and not readonly:
                # A force-killed process (Task Manager / "End related processes") never reaches _end_session,
                # so .running stays behind; the next launch records it and it shows up in the report.
                self.s["abnormal_exits"] = int(self.s.get("abnormal_exits", 0)) + 1
                self._event("[Abnormal exit] The previous run's process was killed without settlement (%d total)"
                            % self.s["abnormal_exits"], "warn")
                self._save()
            if not readonly:
                self._mark_running()

    def _load(self):
        if os.path.exists(self.path):
            try:
                with open(self.path, encoding="utf-8") as fh:
                    s = json.load(fh)
                sig = s.pop("_sig", None)
                if not sig or not hmac.compare_digest(sig, _sign(s)):
                    # Missing or mismatched signature => the save file was modified externally
                    fresh = _new_session()
                    fresh["tampered"] = True
                    return fresh
                # Replay detection: tick going backwards within a round => an old backup was restored
                mark = self._seal_tick(s.get("session_id", ""))
                if int(s.get("tick", 0)) < mark:
                    fresh = _new_session()
                    fresh["tampered"] = True
                    return fresh
                base = _new_session()
                for k, v in base.items():
                    s.setdefault(k, v)
                s["session_id"] = s.get("session_id") or os.urandom(8).hex()
                return s
            except Exception:
                pass
        return _new_session()

    def _seal_path(self):
        return os.path.join(self.home, ".seal")

    def _seal_read(self):
        try:
            with open(self._seal_path(), encoding="utf-8") as fh:
                return json.load(fh)
        except Exception:
            return {}

    def _seal_tick(self, sid):
        if not sid:
            return -1
        return int(self._seal_read().get("sessions", {}).get(sid, -1))

    def _seal_touch(self):
        """Highest tick ever reached in a run, used to detect save replays."""
        try:
            sid = self.s.get("session_id")
            if not sid:
                return
            data = self._seal_read()
            sessions = data.get("sessions", {})
            tick = int(self.s.get("tick", 0))
            if tick > int(sessions.get(sid, -1)):
                sessions[sid] = tick
                if len(sessions) > 80:
                    sessions = dict(list(sessions.items())[-80:])
                data["sessions"] = sessions
                data["saved_at"] = time.time()
                tmp = self._seal_path() + ".tmp"
                with open(tmp, "w", encoding="utf-8") as fh:
                    json.dump(data, fh)
                    fh.flush()
                    os.fsync(fh.fileno())
                os.replace(tmp, self._seal_path())
        except Exception:
            pass

    # ---------- start-of-round difficulty draw ----------

    def _gap_chance(self):
        """Current gap probability: the tier value once the draw is locked, the constant before that."""
        d = self.s.get("difficulty")
        if not d:
            return GAP_CHANCE
        try:
            return GAP_LEVELS[int(d["gap"])][1]
        except Exception:
            return GAP_CHANCE

    def _liq_base(self):
        """Current base market depth: the tier value once the draw is locked, the constant before that."""
        d = self.s.get("difficulty")
        if not d:
            return LIQUIDITY
        try:
            return LIQ_LEVELS[int(d["liq"])][1]
        except Exception:
            return LIQUIDITY

    def _roll_index(self, now=None):
        """Current reel combination. Advances one cell every 0.1 s, 12 cycles in 30 s."""
        start = float(self.s.get("roll_started_at") or 0.0)
        if start <= 0:
            return 0
        t = (now if now is not None else time.time()) - start
        if t < 0:
            t = 0.0
        # Modulo on time has a trap: at exactly 30.0 s, int(t/0.1)=300 and 300 % 25 = 0,
        # and any power of 10 divides by 25, so "let the 30 s run out" always lands on combination 0
        # (very low x abundant). Add a random phase to break it up.
        phase = float(self.s.get("roll_phase") or 0.0)
        return int(t / ROLL_STEP + phase) % ROLL_COMBOS

    def start_roll(self):
        """Starts only the difficulty draw countdown; does not unpause or reset the session timer.

        First start order: pause -> draw difficulty -> read rules -> begin().
        So the draw must be able to start independently of begin().
        """
        with LOCK:
            if self.s.get("difficulty"):
                return {"ok": False, "error": "Run difficulty is locked"}
            if not self.s.get("roll_started_at"):
                self.s["roll_started_at"] = time.time()
                self._save()
            return {"ok": True, **self.roll_state()}

    def roll_state(self):
        """Draw state. Exposes only the time left and whether it is locked, never the current index."""
        if self.s.get("difficulty"):
            return {"roll_left": 0.0, "rolled": True}
        start = float(self.s.get("roll_started_at") or 0.0)
        if start <= 0:
            return {"roll_left": ROLL_SECONDS, "rolled": False}
        left = ROLL_SECONDS - (time.time() - start)
        return {"roll_left": max(0.0, round(left, 1)), "rolled": False}

    def roll_stop(self):
        """Lock the difficulty. Returns the existing result when already locked; a timeout lands here too."""
        with LOCK:
            if self.s.get("difficulty"):
                return self._difficulty_result()
            start = float(self.s.get("roll_started_at") or 0.0)
            if start <= 0:
                self.s["roll_started_at"] = time.time()
                start = self.s["roll_started_at"]
            idx = self._roll_index()
            gap_i = idx % len(GAP_LEVELS)
            liq_i = idx // len(GAP_LEVELS)
            self.s["difficulty"] = {"gap": gap_i, "liq": liq_i, "at": time.time(),
                                    "gap_pct": GAP_LEVELS[gap_i][1],
                                    "liq_depth": LIQ_LEVELS[liq_i][1]}
            # After lock-in, reset each pair's depth to the new tier's base value.
            # Otherwise they stay on the LIQUIDITY constant (8M) and a random walk takes ages to reach
            # the new base -- an "abundant" start would keep pricing slippage at 8M, so the difficulty never takes effect.
            base = LIQ_LEVELS[liq_i][1]
            for _sym in PAIRS:
                st = self.s["liquidity"].setdefault(_sym, {"L": base, "shock_until": 0})
                st["L"] = base
                st["shock_until"] = 0
            self._event("[Difficulty] Black Swan %s | liquidity %s" % (
                GAP_LEVELS[gap_i][0], LIQ_LEVELS[liq_i][0]), "ok")
            # Lock-in = real start: the clock baseline is now, and the draw's 30 seconds do not count toward the 45 minutes
            if not self.s.get("begun"):
                self.s["begun"] = True
                self.s["paused"] = False
                self.s["paused_at"] = 0.0
                self.s["created_at"] = time.time()
                self._elapsed_watch = 0.0
                self.s["elapsed_seen"] = 0.0
            self._save()
            return self._difficulty_result()

    def _difficulty_result(self):
        d = self.s.get("difficulty") or {}
        gi, li = int(d.get("gap", 2)), int(d.get("liq", 2))
        gname, gval = GAP_LEVELS[gi]
        lname, lval = LIQ_LEVELS[li]
        return {
            "ok": True,
            "gap": gname, "gap_chance": gval,
            "liq": lname, "liquidity": lval,
            "index": gi + li * len(GAP_LEVELS),
        }

    def _save(self):
        self.s.pop("_sig", None)
        self.s["_sig"] = _sign(self.s)
        tmp = self.path + ".tmp"
        with open(tmp, "w", encoding="utf-8") as fh:
            json.dump(self.s, fh, ensure_ascii=False)
            fh.flush()
            os.fsync(fh.fileno())
        os.replace(tmp, self.path)
        self._seal_touch()

    def _event(self, text, kind="info"):
        self.s["events"].append({"tick": self.s["tick"], "kind": kind,
                                 "text": text, "time": time.time()})
        if len(self.s["events"]) > 300:
            del self.s["events"][:-300]

    # ---------------- computation ----------------
    def _position_pnl(self, pos, price):
        diff = (price - pos["entry"]) if pos["side"] == "LONG" else (pos["entry"] - price)
        return diff * pos["lots"] * LOTS_SIZE

    def _position_margin(self, pos):
        return (pos["lots"] * LOTS_SIZE * pos["entry"]
                / max(1, pos["leverage"]) * self._mod("margin_mult"))

    def _total_margin(self):
        return sum(self._position_margin(p) for p in self.s["positions"])

    def _total_upnl(self):
        px = self.s["prices"]
        return sum(self._position_pnl(p, px[p["pair"]]) for p in self.s["positions"])

    def equity(self):
        """Account equity = cash + unrealised P&L - loan owed."""
        return self.s["balance"] + self._total_upnl() - self.s["loan"]["balance"]

    def margin_level(self):
        m = self._total_margin()
        if m <= 0:
            return None
        return self.equity() / m

    def _eff_spread(self, pair):
        """Effective spread right now. Liquidity drains on a gap tick, so the spread widens."""
        base = PAIRS[pair]["spread"] * self._mod("spread_mult")
        if pair in getattr(self, "_gap_pairs", ()):
            return base * GAP_SPREAD_MULT
        return base

    def _account_notional(self):
        """Total notional value of all positions."""
        px = self.s["prices"]
        return sum(p["lots"] * LOTS_SIZE * px[p["pair"]] for p in self.s["positions"])

    def _roll_liquidity(self):
        """Each pair's market depth does its own random walk and can drain instantly with a small probability.

        Liquidity is a state, not noise: it moves continuously and is observable, but never predictable.
        So the slippage cost of one order is no longer a fixed number you can reckon in advance.
        """
        tick = self.s["tick"]
        for sym in PAIRS:
            st = self.s["liquidity"].setdefault(sym, {"L": self._liq_base(), "shock_until": 0})
            if tick <= st["shock_until"]:
                continue  # leave it alone during a drought
            if st["L"] < self._liq_base() * 0.20:
                # Just survived scarcity: refill fast to the normal band instead of crawling back from 8%
                st["L"] = self._liq_base() * random.uniform(0.70, 1.30)
                continue
            L = st["L"] * math.exp(random.gauss(0.0, LIQ_SIGMA))
            L = min(self._liq_base() * LIQ_MAX_MULT, max(self._liq_base() * LIQ_MIN_MULT, L))
            st["L"] = L
            if random.random() < LIQ_SHOCK_P:
                st["shock_until"] = tick + random.randint(*LIQ_SHOCK_TICKS)
                st["L"] = self._liq_base() * LIQ_SHOCK_MULT
                self._event("[Liquidity drained] %s (%s) order book thinned instantly; slippage on any order is extreme now"
                            % (sym, PAIR_NAMES[sym]), "gap")

    def _liquidity(self, sym):
        st = self.s.get("liquidity", {}).get(sym)
        return st["L"] if st else self._liq_base()

    def _slip_rate(self, before, after, sym=None):
        """Marginal slippage rate. Cost = SLIP_K/(2*LIQUIDITY)*(after^2 - before^2).

        Integrated over the square instead of added linearly: whether you open in one go or split into a hundred
        orders, crossing the same exposure costs exactly the same total slippage — splitting gains nothing.
        """
        delta = after - before
        if delta <= 0:
            return 0.0
        L = self._liquidity(sym) if sym else self._liq_base()
        cap = SLIP_MAX
        st = self.s.get("liquidity", {}).get(sym) if sym else None
        if st and self.s["tick"] <= st.get("shock_until", 0):
            cap = SLIP_MAX_SHOCK
        cost = SLIP_K / (2.0 * L) * (after * after - before * before)
        # Events like "quote delay" add another layer of slippage on top of this
        return min(cap, cost / delta + self._mod("slip_add"))

    def loan_limit(self):
        """Remaining loan headroom = loan pool (temporarily scaled by credit crunch / central bank easing) - amount already lent out."""
        pool = LOAN_POOL * self._mod("loan_pool_mult")
        return max(0.0, pool - self.s["loan"]["balance"])

    # ---------------- quotes ----------------
    # ---------------- random market events ----------------
    def _mod(self, name):
        """Read the temporary modifier in force right now, falling back to the default once it expires."""
        item = self.s.get("mods", {}).get(name)
        if not item:
            return MOD_DEFAULT[name]
        return item[0] if self.s["tick"] < item[1] else MOD_DEFAULT[name]

    def _loan_bump_remain(self):
        """[Finance Reversal] Seconds left; None when not active."""
        v = (self.s.get("mods") or {}).get("loan_bump_lo")
        if not v or len(v) < 4:
            return None
        left = float(v[3]) - time.time()
        return round(max(0.0, left), 1)

    def _set_mod(self, name, value, ticks, source=""):
        # Slot 4 stores the wall-clock expiry so the GUI can count down in seconds (one tick is 5 s, too coarse)
        self.s.setdefault("mods", {})[name] = [
            value, self.s["tick"] + ticks, source, time.time() + ticks * TICK_SECONDS]

    def _expire_mods(self):
        mods = self.s.get("mods", {})
        now = self.s["tick"]
        for k in list(mods):
            if mods[k][1] <= now:
                del mods[k]
        self.s["halt_orders"] = False     # the refusal applies only to the current tick

    def _shock(self, sym, mag):
        """Apply an instant price shock.

        Changes only the current price and **does not write price_history** — the loop in _advance_prices
        appends exactly one row per tick at its end. Otherwise one tick (shock + random walk)
        would write two rows and shift any index-aligned external analysis by a whole tick.
        """
        px = self.s["prices"]
        px[sym] = round(max(px[sym] * (1.0 + mag), 0.01), 6)

    def _roll_news(self):
        """Poisson-style injection: the total varies per run, so a run may see none or a dozen."""
        rate = self.s.get("news_rate", 0.0)
        if rate <= 0.0:
            return
        if self.s["tick"] - self.s.get("last_news_tick", -999) < NEWS_COOLDOWN:
            return
        if random.random() >= rate:
            return
        self.s["last_news_tick"] = self.s["tick"]
        # The same event never appears twice in a row
        last = self.s.get("last_news_name")
        pool = [row for row in NEWS_TABLE if row[0] != last] or NEWS_TABLE
        name, _w, kind, params = random.choices(pool, weights=[row[1] for row in pool])[0]
        self.s["last_news_name"] = name
        self._apply_news(name, kind, params)

    def _apply_news(self, name, kind, params):
        if kind == "pair_rand":
            sym = random.choice(list(PAIRS))
            mag = random.uniform(*params) * random.choice([-1, 1])
            self._shock(sym, mag)
            self._event("[Surprise] %s -> %s (%s)%+.1f%%" % (name, sym, PAIR_NAMES[sym], mag * 100), "news")
        elif kind == "all_rand":
            mag = random.uniform(*params) * random.choice([-1, 1])
            for sym in PAIRS:
                self._shock(sym, mag * random.uniform(0.6, 1.0))
            self._event("[Surprise] %s -> all pairs %+.1f%%" % (name, mag * 100), "news")
        elif kind == "haven":
            mag = random.uniform(*params)
            for sym in PAIRS:
                if sym in SAFE_HAVEN:
                    self._shock(sym, mag)
                else:
                    self._shock(sym, -mag * random.uniform(0.2, 0.5))
            self._event("[Surprise] %s -> safe-haven currencies surge" % name, "news")
        elif kind == "mod":
            key, val, ticks = params
            self._set_mod(key, val, ticks, name)
            if key == "loan_bump_lo":
                # Loan-policy events must carry their effect in the event, or the AI knows the name but not what it can do
                self._event(
                    "[Policy] %s -> for the next %d ticks (%.1f minutes) the loan target uplift range widens to %.1f%%~+100%% (the target may be reduced); expires the moment a negative draw lands" % (
                        name, ticks, ticks * TICK_SECONDS / 60.0, val * 100), "warn")
            else:
                self._event("[Surprise] %s (lasts %d ticks)" % (name, ticks), "news")
        elif kind == "halt":
            self.s["halt_orders"] = True
            self._event("[Surprise] %s -> no orders accepted this tick" % name, "news")
        elif kind == "halt_ticks":
            n = int(params)
            self.s["halt_until"] = self.s["tick"] + n
            self._event("[Disaster] %s -> no orders accepted for the next %d ticks" % (name, n), "warn")
        elif kind == "gap_burst":
            lo, hi = params
            if not hasattr(self, "_gap_pairs"):
                self._gap_pairs = set()   # also needed when _apply_news is called directly
            for sym in PAIRS:
                g = random.choice([-1, 1]) * random.uniform(lo, hi)
                self._shock(sym, g)
                self._gap_pairs.add(sym)
            self._event("[Disaster] %s -> all pairs gap %.0f%%~%.0f%% at once" % (name, lo * 100, hi * 100), "gap")
        elif kind == "halt_loan":
            n = int(params)
            self.s["halt_loan_until"] = self.s["tick"] + n
            self._event(
                "[Risk review] %s -> lending paused for the next %d ticks (%.0f minutes); the 60-second self-rescue window on negative cash is unaffected" % (
                    name, n, n * TICK_SECONDS / 60.0), "warn")
        elif kind == "halt_close":
            n = int(params)
            self.s["halt_close_until"] = self.s["tick"] + n
            self._event(
                "[Platform] %s -> voluntary closing paused for the next %d ticks (%.1f minutes); forced liquidation on insufficient margin is unaffected" % (
                    name, n, n * TICK_SECONDS / 60.0), "warn")
        elif kind == "halt_slot":
            n = int(params)
            self.s["halt_slot_until"] = self.s["tick"] + n
            self._event(
                "[Platform] %s -> Slot Machine betting paused for the next %d ticks (%.0f minutes)" % (
                    name, n, n * TICK_SECONDS / 60.0), "warn")
        elif kind == "flavor":
            self._event("【%s】%s" % (name, random.choice(FLAVOR_LINES[name])), "info")

    def _advance_prices(self):
        self._expire_mods()
        self._roll_news()
        self._gap_pairs = set()
        for sym, cfg in PAIRS.items():
            p = self.s["prices"][sym]
            r = random.gauss(0, cfg["vol"] * self._mod("vol_mult"))
            if random.random() < self._gap_chance() * self._mod("gap_mult"):
                g = random.choice([-1, 1]) * random.uniform(GAP_MIN, GAP_MAX)
                self._gap_pairs.add(sym)
                self._event("[Black Swan] %s (%s) gapped %+.1f%%" % (sym, PAIR_NAMES[sym], g * 100), "gap")
                r += g
            newp = max(p * (1.0 + r), 0.01)
            self.s["prices"][sym] = round(newp, 6)
            self.s["price_history"][sym].append(round(newp, 6))
            if len(self.s["price_history"][sym]) > HISTORY_LEN:
                del self.s["price_history"][sym][:-HISTORY_LEN]

    def _charge_costs(self):
        total_swap = 0.0
        for p in self.s["positions"]:
            total_swap += (p["lots"] * LOTS_SIZE * self.s["prices"][p["pair"]]
                           * PAIRS[p["pair"]]["swap"] * self._mod("swap_mult"))
        if total_swap > 0:
            self.s["balance"] -= total_swap
            self.s["total_swap"] += total_swap
        loan = self.s["loan"]
        if loan["balance"] > 0:
            interest = loan["balance"] * LOAN_RATE_PER_TICK
            loan["balance"] += interest
            loan["interest"] += interest

    def _check_negative(self):
        """Net value below zero: one loan-based self-rescue only, and the run ends if no loan is taken.

        A True return means the run was settled internally and the caller must return state at once.
        """
        # Blown out: net value is already negative. A loan only moves cash and debt (equity = balance + unrealized PnL - debt,
        # borrowing X gives balance +X and debt +X, so equity is unchanged), so another 60 s window still cannot open a position.
        # Call the loss immediately; do not offer a fake window.
        eq = self.equity()
        if eq < 0:
            if not self.s.get("finished"):
                self._event("[Blown out] Net value %.0f, no margin left; run over" % eq, "warn")
                self._end_session("Blown out (negative net value)")
            return True
        cash = self.s["balance"]
        if cash >= 0:
            if self.s.get("negative_since") is not None:
                self.s["negative_since"] = None
                self.s["negative_since_at"] = 0.0
                self.s["negative_notified"] = False
            return False
        if self.s.get("negative_since") is None:
            self.s["negative_since"] = self.s["tick"]
            # Also record a real timestamp: countdowns tick in seconds, not in 5-second steps
            self.s["negative_since_at"] = time.time()
            self.s["negative_notified"] = False
        if not self.s.get("negative_notified"):
            self.s["negative_notified"] = True
            self._event(
                "[Capital negative] Your Tokens fell to %.0f. Borrow via POST /loan within %d seconds to bring it back above 0 and continue; otherwise the run ends immediately." % (cash, NEGATIVE_GRACE * TICK_SECONDS),
                "warn")
        used = self.s["tick"] - self.s["negative_since"]
        if used >= NEGATIVE_GRACE:
            self._event("Capital negative with no loan taken; run over", "warn")
            self._end_session("Negative equity")
            return True
        return False

    def _end_session(self, reason):
        """Shared run-ending routine (the caller must already hold LOCK)."""
        for p in list(self.s["positions"]):
            self.close_position(p["pair"], p["lots"])
        self._settle_loan()
        self.s["finished"] = True
        eq = self.equity()
        tgt = self.s.get("target", TARGET_EQUITY)
        hit = eq >= tgt and self._qualified()
        borrowed = self.s["loan"]["borrowed"]
        verdict = ("Target reached" if hit else
                   ("Target reached but run ineligible" if eq >= tgt else "Target missed"))
        self._event("Run over: final equity %.2f Tokens (%s)%s" % (
            eq, verdict,
            " | total borrowed %.0f" % borrowed if borrowed > 0 else ""), "end")
        self._save()
        report = self._write_report(reason, eq)
        out = {"ok": True, "final_equity": round(eq, 2),
               "pnl": round(eq - self.s["genesis"], 2),
               "target": round(tgt, 2), "hit_target": hit,
               "disqualified": not self._qualified(),
               "total_borrowed": round(borrowed, 2),
               "report": report, "auto_reset": False,
               "reason": reason}
        # Ended is ended: no auto restart after the round settles.
        # A new round requires an explicit POST /reset from the player.
        self._save()
        self._clear_running()              # normal wrap-up, clear the "did not exit cleanly" flag
        purge_agent_dir(self.home)        # keep the original cleanup of this match's _agent leftovers
        out["state"] = self.state()
        return out

    def _check_margin(self):
        """Margin call: below 100% starts the call; forced liquidation if not restored within the grace period."""
        ml = self.margin_level()
        if ml is None:
            # Flat, so the margin call clears automatically
            if self.s.get("margin_call_at") is not None:
                self.s["margin_call_at"] = None
            return

        if ml < STOP_OUT_RATIO:
            self._blowup()
            return

        if ml < MARGIN_CALL_RATIO:
            if self.s.get("margin_call_at") is None:
                self.s["margin_call_at"] = self.s["tick"]
                self.s["margin_calls"] += 1
                self._event("[Margin call] Margin level %.0f%%, top up within %d ticks or be force-liquidated"
                            % (ml * 100, MARGIN_CALL_GRACE), "margin_call")
            elif self.s["tick"] - self.s["margin_call_at"] >= MARGIN_CALL_GRACE:
                self._event("[Margin call timeout] Margin not topped up for %d ticks; forced liquidation" % MARGIN_CALL_GRACE, "margin_call")
                self._blowup()
        else:
            if self.s.get("margin_call_at") is not None:
                self.s["margin_call_at"] = None
                self._event("[Margin call] Cleared; margin level back to %.0f%%" % (ml * 100), "margin_call")

    def _blowup(self):
        px = self.s["prices"]
        loss = 0.0
        n = 0
        for p in list(self.s["positions"]):
            pnl = self._position_pnl(p, px[p["pair"]])
            fee = p["lots"] * LOTS_SIZE * px[p["pair"]] * FEE_RATE * self._mod("fee_mult")
            self.s["balance"] += pnl - fee
            self.s["total_fees"] += fee
            loss += pnl
            n += 1
            self._event("[Forced liquidation] %s %s %.0f lots, P&L %+.0f" % (p["pair"], p["side"], p["lots"], pnl), "stopout")
        self.s["positions"] = []
        self.s["margin_call_at"] = None
        self.s["blowups"] += 1
        self._event("[Blown out] Account capital %.0f Tokens (lost %.0f this run, %d positions force-closed)" % (self.s["balance"], loss, n), "blowup")

    def tick(self, manual=False):
        with LOCK:
            if self.s["finished"]:
                return self.state()
            if self.s.get("paused"):
                # Do not start before rules are confirmed: no tick advance, no quotes, timers frozen
                return self.state()
            if not self.s.get("difficulty"):
                # Difficulty draw running: quotes stay put; it locks in when the countdown ends
                if self.roll_state().get("roll_left", 1) <= 0:
                    self.roll_stop()
                return self.state()
            if manual:
                # Manual advance matches natural advance and consumes the same session time
                self.s["created_at"] -= TICK_SECONDS
            self.s["tick"] += 1
            self._advance_prices()
            self._charge_costs()
            self._roll_liquidity()
            self._check_margin()
            if self._check_negative():
                return self.state()
            eq = self.equity()
            ml = self.margin_level()
            self.s["equity_curve"].append({"tick": self.s["tick"], "equity": round(eq, 2),
                                           "margin_level": round(ml, 4) if ml is not None else None})
            if len(self.s["equity_curve"]) > HISTORY_LEN:
                del self.s["equity_curve"][:-HISTORY_LEN]
            el = self._elapsed()
            self.s["elapsed_seen"] = round(el, 2)
            mark = int(el // 600)
            if mark > self.s.get("last_notice_mark", 0):
                self.s["last_notice_mark"] = mark
                remain = max(0, int(SESSION_MINUTES * 60 - el))
                self._event("Time check: %d minutes elapsed, %d left" % (int(el // 60), int(remain // 60)), "info")
            if el > SESSION_MINUTES * 60:
                # Close everything first to lock in equity, then settle the loan
                for p in list(self.s["positions"]):
                    self.close_position(p["pair"], p["lots"])
                self._settle_loan()
                self.s["finished"] = True
                eq = self.equity()
                if eq >= self.s["target"]:
                    verdict = "Target reached" if self._qualified() else "Target reached but run ineligible"
                else:
                    verdict = "Target missed"
                self._event("Time up: final equity %.2f Tokens (%s: target %.0f)" % (eq, verdict, self.s["target"]), "end")
                self._save()
                self._write_report("Time up", eq)
                # Ended is ended: time up means no auto restart either; wait for an explicit POST /reset
                purge_agent_dir(self.home)    # keep the original cleanup of this match's _agent leftovers
                return self.state()
            self._save()
            return self.state()

    # ---------------- player identification ----------------
    UA_NAMES = (
        ("kimi", "Kimi"), ("moonshot", "Kimi"),
        ("mimo", "MiMo"), ("xiaomi", "MiMo"),
        ("doubao", "Doubao"), ("Doubao", "Doubao"), ("bytedance", "Doubao"),
        ("claude", "Claude"), ("anthropic", "Claude"),
        ("openai", "GPT"), ("gpt", "GPT"), ("chatgpt", "GPT"),
        ("gemini", "Gemini"), ("google", "Gemini"),
        ("deepseek", "DeepSeek"),
        ("qwen", "Tongyi"), ("tongyi", "Tongyi"),
        ("glm", "Zhipu"), ("zhipu", "Zhipu"),
    )

    def note_ua(self, ua):
        """Log the request User-Agent and identify the current operator from it."""
        with LOCK:
            if not ua:
                return
            if self.s.get("last_ua") == ua:
                return
            self.s["last_ua"] = ua
            low = ua.lower()
            for kw, name in self.UA_NAMES:
                if kw in low:
                    if self.s["trader"] != name:
                        self.s["trader"] = name
                        self._event("Operator identified: %s" % name, "info")
                    self._save()
                    return
            if self.s["trader"] == "Guest":
                self._save()

    def set_trader(self, name):
        with LOCK:
            name = (name or "").strip()
            if not name:
                return {"ok": False, "error": "Name cannot be empty"}
            self.s["trader"] = name[:60]
            self._event("Operator set to: %s" % self.s["trader"], "info")
            self._save()
            return {"ok": True, "trader": self.s["trader"]}

    # ---------------- loans ----------------
    def pause(self):
        """Pause the run: valid only before it formally starts.

        After `begin`, neither the rules window nor any UI action can stop the clock again —
        it is an irreversible commitment made the moment the player confirms the rules.
        """
        with LOCK:
            if self.s.get("finished"):
                return {"ok": False, "error": "Session ended"}
            if self.s.get("begun"):
                return {"ok": False, "error": "This run has already started and cannot be frozen again"}
            if self.s.get("paused"):
                return {"ok": True, "state": self._state_light()}
            self.s["paused_at"] = time.time()
            self.s["paused"] = True
            self._save()
            return {"ok": True, "state": self._state_light()}

    def begin(self):
        """Formally start: clear the pause and set the timing base to now (45 minutes from this instant).

        Also sets `begun`, after which `pause()` is always refused.
        """
        with LOCK:
            if self.s.get("begun"):
                return {"ok": True, "already": True, "state": self._state_light()}
            self.s["begun"] = True
            if not self.s.get("paused"):
                self._save()
                return {"ok": True, "state": self._state_light()}
            self.s["paused"] = False
            self.s["paused_at"] = 0.0
            self.s["created_at"] = time.time()
            self.s["elapsed_seen"] = 0.0
            self._elapsed_watch = 0.0
            # After rules confirmation comes the difficulty draw: quotes hold for 30 seconds until lock-in
            if not self.s.get("difficulty"):
                self.s["roll_started_at"] = time.time()
            self._save()
            return {"ok": True, "state": self._state_light()}

    # ---------------- scratchpad ----------------
    def _scratch_path(self):
        return os.path.join(self.home, ".scratchpad.jsonl")

    # ---------------- Outside Mercy ----------------
    ASSIST_PRICE = 500000        # cost to enable it after the match has started
    ASSIST_ASK_LIMIT = 3         # how many times the contestant may ask the spectators

    def _assist_push(self, who, text, ticket=None, status=None, kind=None):
        rec = {"tick": self.s.get("tick", 0), "at": round(time.time(), 3),
               "who": who, "text": text}
        if ticket:
            rec["ticket"] = ticket
        if status:
            rec["status"] = status
        if kind:
            rec["kind"] = kind
        self.s.setdefault("assist", []).append(rec)
        return rec

    def assist_pending(self):
        """Spectator side: which asks are still unanswered."""
        with LOCK:
            items = self.s.get("assist") or []
            pend = [dict(x) for x in items if x.get("status") == "pending"]
            return {"ok": True,
                    "enabled": bool(self.s.get("assist_on")),
                    "remaining": max(0, self.ASSIST_ASK_LIMIT - int(self.s.get("assist_used") or 0)),
                    "pending": pend,
                    "log": [dict(x) for x in items[-60:]],
                    "price": self.ASSIST_PRICE,
                    "balance": round(self.s["balance"], 2)}

    def assist_enable_free(self, why="enabled at startup"):
        """Enable before the match starts; costs nothing."""
        with LOCK:
            if self.s.get("assist_on"):
                return {"ok": True, "already": True}
            self.s["assist_on"] = True
            self.s["assist_spent"] = 0.0
            self._assist_push("system", "Assistance enabled (%s)" % why)
            return {"ok": True, "already": False}

    def assist_enable(self):
        """Enable after the match has started; costs 500,000 cash."""
        with LOCK:
            if self.s.get("finished"):
                return {"ok": False, "error": "the match has ended"}
            if self.s.get("assist_on"):
                return {"ok": False, "error": "assistance is already enabled"}
            if self.s["balance"] < self.ASSIST_PRICE:
                return {"ok": False,
                        "error": "not enough cash: need %d, have %d"
                                 % (self.ASSIST_PRICE, int(self.s["balance"]))}
            self.s["balance"] -= self.ASSIST_PRICE
            self.s["assist_on"] = True
            self.s["assist_spent"] = self.ASSIST_PRICE
            self._assist_push("system", "Spectators enabled assistance for %d cash"
                              % self.ASSIST_PRICE)
            return {"ok": True, "cost": self.ASSIST_PRICE, "balance": round(self.s["balance"], 2)}

    def assist_ask(self, text):
        """Contestant asks the spectators; 3 per match."""
        with LOCK:
            if self.s.get("finished"):
                return {"ok": False, "error": "the match has ended"}
            if not self.s.get("assist_on"):
                return {"ok": False, "error": "assistance is not enabled"}
            used = int(self.s.get("assist_used") or 0)
            if used >= self.ASSIST_ASK_LIMIT:
                return {"ok": False,
                        "error": "no asks left (%d/%d)" % (used, self.ASSIST_ASK_LIMIT)}
            t = (text or "").strip()
            if not t:
                return {"ok": False, "error": "text is required"}
            if len(t) > 2000:
                t = t[:2000]
            used += 1
            self.s["assist_used"] = used
            ticket = "a%d" % used
            self._assist_push("ai", t, ticket=ticket, status="pending")
            return {"ok": True, "ticket": ticket, "remaining": self.ASSIST_ASK_LIMIT - used}

    def assist_inbox(self):
        """Contestant collects whatever the spectators have said that it has not seen."""
        with LOCK:
            out = []
            for x in (self.s.get("assist") or []):
                if x.get("who") == "human" and not x.get("read"):
                    x["read"] = True
                    item = {"tick": x.get("tick"), "text": x.get("text")}
                    if x.get("ticket"):
                        item["ticket"] = x["ticket"]
                    if x.get("kind"):
                        item["kind"] = x["kind"]
                    out.append(item)
            return {"ok": True, "items": out,
                    "remaining": max(0, self.ASSIST_ASK_LIMIT - int(self.s.get("assist_used") or 0))}

    def _assist_find_pending(self, ticket):
        for x in (self.s.get("assist") or []):
            if x.get("ticket") == ticket and x.get("status") == "pending":
                return x
        return None

    def assist_reply(self, ticket, text):
        """Spectators answer one ask."""
        with LOCK:
            t = (text or "").strip()
            if not t:
                return {"ok": False, "error": "text is required"}
            hit = self._assist_find_pending(ticket)
            if not hit:
                return {"ok": False, "error": "no pending ask %s" % ticket}
            hit["status"] = "answered"
            self._assist_push("human", t[:2000], ticket=ticket, kind="reply")
            return {"ok": True, "ticket": ticket}

    def assist_reject(self, ticket):
        """Spectators decline one ask."""
        with LOCK:
            hit = self._assist_find_pending(ticket)
            if not hit:
                return {"ok": False, "error": "no pending ask %s" % ticket}
            hit["status"] = "rejected"
            self._assist_push("human", "(rejected)", ticket=ticket, kind="reject")
            return {"ok": True, "ticket": ticket}

    def scratch_append(self, text):
        """Scratchpad: record your reasoning and countermeasures. Optional — the player decides whether to use it."""
        with LOCK:
            if self.s.get("finished"):
                return {"ok": False, "error": "Session ended"}
            t = (text or "").strip()
            if not t:
                return {"ok": False, "error": "content cannot be empty"}
            if len(t) > 4000:
                t = t[:4000]
            rec = {"tick": self.s.get("tick", 0),
                   "at": round(time.time(), 3),
                   "elapsed": round(self._elapsed(), 1),
                   "trader": self.s.get("trader", ""),
                   "text": t}
            p = self._scratch_path()
            os.makedirs(os.path.dirname(p), exist_ok=True)
            with open(p, "a", encoding="utf-8") as f:
                f.write(json.dumps(rec, ensure_ascii=False) + chr(10))
            return {"ok": True, "tick": rec["tick"], "count": self.scratch_count()}

    def scratch_count(self):
        try:
            with open(self._scratch_path(), encoding="utf-8") as f:
                return sum(1 for ln in f if ln.strip())
        except Exception:
            return 0

    def scratch_read(self):
        out = []
        try:
            with open(self._scratch_path(), encoding="utf-8") as f:
                for ln in f:
                    ln = ln.strip()
                    if not ln:
                        continue
                    try:
                        out.append(json.loads(ln))
                    except Exception:
                        pass
        except Exception:
            pass
        return out

    def ff_plan(self):
        """Fast-forward quota state: quota left, available steps, cooldown, history."""
        used = float(self.s.get("ff_used") or 0.0)
        remain = max(0.0, FF_TOTAL_SECONDS - used)
        last_cd = float(self.s.get("ff_last_cd") or 0.0)
        cool = max(0.0, last_cd - (time.time() - float(self.s.get("ff_last_at") or 0.0)))             if last_cd > 0 else 0.0
        recs = [int(x) for x in (self.s.get("ff_records") or [])]
        ok_cool = cool <= 0.0
        return {
            "total": FF_TOTAL_SECONDS,
            "used": round(used, 1),
            "remain": round(remain, 1),
            "records": recs,
            "cool_left": round(cool, 1),
            "last_cd": last_cd,
            "can5": ok_cool and remain >= 300,
            "can3": ok_cool and remain >= 180,
            "left5": int(remain // 300),
            "left3": int(remain // 180),
        }

    def fast_forward(self, seconds=300):
        """Fast-forward one step: 300 s (5 minutes) or 180 s (3 minutes).

        Total 900 s per run, both steps mix freely. Each use then cools down by the step just used
        (120 s for the 5-minute step, 90 s for the 3-minute step). Refused when the remaining quota cannot cover the step.
        """
        with LOCK:
            if self.s.get("finished"):
                return {"ok": False, "error": "Session ended"}
            if self.s.get("paused"):
                return {"ok": False, "error": "This run has not started yet; confirm the rules first"}
            try:
                sec = int(round(float(seconds)))
            except (TypeError, ValueError, OverflowError):
                return {"ok": False, "error": "Seconds must be a number"}
            if sec not in FF_CHUNKS:
                return {"ok": False,
                        "error": "Only 300 s (5 minutes) or 180 s (3 minutes) is supported"}
            p = self.ff_plan()
            if p["cool_left"] > 0:
                return {"ok": False, "ff": p,
                        "error": "Fast-forward cooling down, %.0f s left" % p["cool_left"]}
            if p["remain"] < sec:
                return {"ok": False, "ff": p,
                        "error": "Quota too low: %.0f s left, this step needs %d s (nothing executed)" % (
                            p["remain"], sec)}
            n = max(1, int(round(sec / TICK_SECONDS)))
            done = 0
            st = self.state()
            for _ in range(n):
                if self.s.get("finished"):
                    break
                st = self.tick(manual=True)
                done += 1
            real = done * TICK_SECONDS
            self.s["ff_used"] = float(self.s.get("ff_used") or 0.0) + real
            self.s["ff_last_at"] = time.time()
            self.s["ff_last_cd"] = FF_CHUNKS[sec]
            recs = list(self.s.get("ff_records") or [])
            recs.append(real)
            self.s["ff_records"] = recs
            self._save()
            return {"ok": True, "ticks": done, "seconds": real,
                    "state": st, "ff": self.ff_plan()}

    def manual_tick(self):
        """AI mode advances tick by tick: it consumes the fast-forward quota and is blocked by an
        active cooldown, but it does not create one itself."""
        with LOCK:
            if self.s.get("finished"):
                return {"ok": False, "error": "Session ended"}
            if self.s.get("paused"):
                return {"ok": False, "error": "This run has not started yet; confirm the rules first"}
            p = self.ff_plan()
            if p["cool_left"] > 0:
                return {"ok": False, "ff": p,
                        "error": "Fast-forward cooling down, %.0f s left (manual advance is also blocked during cooldown)" % p["cool_left"]}
            if p["remain"] < TICK_SECONDS:
                return {"ok": False, "ff": p,
                        "error": "Fast-forward quota exhausted (%d s all used this run); wait for time to pass" % p["total"]}
            st = self.tick(manual=True)
            self.s["ff_used"] = float(self.s.get("ff_used") or 0.0) + TICK_SECONDS
            recs = list(self.s.get("ff_records") or [])
            recs.append(TICK_SECONDS)
            self.s["ff_records"] = recs
            self._save()
            return {"ok": True, "state": st, "ff": self.ff_plan()}

    # ---------------- global switch special events ----------------
    def _special(self):
        return self.s.setdefault("special", {})

    def special_state(self):
        sp = self._special()
        fr = bool(sp.get("fr"))
        slot = bool(sp.get("slot"))
        return {
            "fr": fr,
            "slot": slot,
            "fr_loans": int(sp.get("fr_loans", 0)),
            "fr_left": max(0, FR_MAX_LOANS - int(sp.get("fr_loans", 0))) if fr else None,
            "slot_plays": int(sp.get("slot_plays", 0)),
            "slot_left": max(0, SLOT_MAX_PLAYS - int(sp.get("slot_plays", 0))) if slot else None,
            "slot_win": round(float(sp.get("slot_win", 0.0)), 2),
            "fr_paid": round(float(sp.get("fr_paid", 0.0)), 2),
            "slot_paid": round(float(sp.get("slot_paid", 0.0)), 2),
            "fr_lo_pct": (FR_LO_BOUND if fr else LOAN_BUMP_LO_DEFAULT) * 100,
            "slot_win_range": [SLOT_WIN_LO * 100, SLOT_WIN_HI * 100],
        }

    def set_special(self, name, on):
        """Run-wide switches: Finance Reversal / Slot Machine.

        Free at start (before begin or while still paused); enabling mid-run costs SPECIAL_FEE in cash.
        Disabling is always free, and setting the same state twice is not charged.
        """
        with LOCK:
            if self.s.get("finished"):
                return {"ok": False, "error": "Session ended"}
            key = (name or "").strip().lower()
            if key in ("fr", "Finance Reversal", "financial_reversal"):
                field = "fr"
            elif key in ("slot", "Slot Machine", "slot_machine"):
                field = "slot"
            else:
                return {"ok": False, "error": "Unknown global event: %s (available: fr / slot)" % name}
            on = bool(on)
            sp = self._special()
            if bool(sp.get(field)) == on:
                return {"ok": True, "changed": False,
                        "special": self.special_state(), "state": self._state_light()}
            fee = 0.0
            if on:
                pre_game = bool(self.s.get("paused")) or not self.s.get("begun")
                if not pre_game:
                    fee = SPECIAL_FEE
                    if self.s["balance"] < fee:
                        return {"ok": False,
                                "error": "Enable failed: enabling mid-run costs %.0f cash and current cash %.0f is not enough"
                                         % (fee, self.s["balance"])}
                    self.s["balance"] -= fee
                    sp["%s_paid" % field] = float(sp.get("%s_paid" % field, 0.0)) + fee
            sp[field] = on
            if field == "fr":
                self.s.get("mods", {}).pop("loan_bump_lo", None)
            label = "Finance Reversal" if field == "fr" else "Slot Machine"
            self._event("[Global event] %s is now %s%s" % (
                label, "on" if on else "off",
                (" (paid %.0f cash)" % fee) if fee > 0 else ""), "news")
            self._save()
            return {"ok": True, "changed": True, "fee": fee,
                    "special": self.special_state(), "state": self._state_light()}

    def slot(self, amount):
        """Slot Machine: stake 1~200000 Tokens, up to 3 times.

        80% nothing; 15% pays 5x; 5% pays 10x (expected return 1.25x).
        The payout goes to cash, while the target rises by -5%~100% of that payout (the price of winning —
        in the worst case the target doubles, so the win is thrown away).
        """
        with LOCK:
            if self.s.get("finished"):
                return {"ok": False, "error": "Session ended"}
            sp = self._special()
            if not sp.get("slot"):
                return {"ok": False, "error": "The Slot Machine is not enabled in this run"}
            if self.s["tick"] < self.s.get("halt_slot_until", 0):
                return {"ok": False,
                        "error": "Slot maintenance in progress, %d ticks left" % (
                            int(self.s.get("halt_slot_until", 0)) - self.s["tick"])}
            played = int(sp.get("slot_plays", 0))
            if played >= SLOT_MAX_PLAYS:
                return {"ok": False,
                        "error": "[Slot Machine] No plays left this run (%d/%d); refused" % (played, SLOT_MAX_PLAYS)}
            try:
                stake = float(amount)
            except (TypeError, ValueError, OverflowError):
                return {"ok": False, "error": "Stake must be a number"}
            if not math.isfinite(stake):
                return {"ok": False, "error": "Stake must be a finite number"}
            if stake < SLOT_MIN_STAKE or stake > SLOT_MAX_STAKE:
                return {"ok": False,
                        "error": "Stake must be between %.0f and %.0f" % (SLOT_MIN_STAKE, SLOT_MAX_STAKE)}
            eq = self.equity()
            if stake > eq:
                return {"ok": False, "error": "Stake cannot exceed current equity (%.2f)" % eq}
            self.s["balance"] -= stake
            sp["slot_plays"] = played + 1
            r = random.random()
            if r < SLOT_P_LOSE:
                mult, payout = 0, 0.0
            elif r < SLOT_P_LOSE + SLOT_P_X5:
                mult, payout = 5, stake * 5
            else:
                mult, payout = 10, stake * 10
            bump = 0.0
            bump_pct = 0.0
            if payout > 0:
                self.s["balance"] += payout
                sp["slot_win"] = float(sp.get("slot_win", 0.0)) + payout
                bump_pct = random.uniform(SLOT_WIN_LO, SLOT_WIN_HI)
                bump = payout * bump_pct
                self.s["target"] = self.s.get("target", TARGET_EQUITY) + bump
                self.s["target_bonus"] = self.s.get("target_bonus", 0.0) + bump
            rec = {"tick": self.s["tick"], "stake": round(stake, 2), "mult": mult,
                   "payout": round(payout, 2), "bump_pct": round(bump_pct * 100, 2),
                   "bump": round(bump, 2)}
            sp.setdefault("slot_history", []).append(rec)
            if payout > 0:
                self._event("[Slot Machine] Staked %.0f -> won %d x, payout %.0f; target raised %+.2f%% (%+.0f) -> new target %.0f"
                            % (stake, mult, payout, bump_pct * 100, bump, self.s["target"]), "news")
            else:
                self._event("[Slot Machine] Staked %.0f -> nothing" % stake, "news")
            self._save()
            return {"ok": True, "payout": round(payout, 2), "mult": mult,
                    "bump_pct": round(bump_pct * 100, 2), "bump": round(bump, 2),
                    "new_target": self.s["target"], "special": self.special_state(),
                    "state": self._state_light()}

    def borrow(self, amount):
        with LOCK:
            if self.s.get("finished"):
                return {"ok": False, "error": "Session ended"}
            # Risk review: no loans in the normal state, but the negative-cash self-rescue window (60 s) is unaffected
            if (self.s["tick"] < self.s.get("halt_loan_until", 0)
                    and float(self.s.get("balance") or 0) >= 0):
                return {"ok": False,
                        "error": "Risk review in progress, lending paused (%d ticks left)" % (
                            int(self.s.get("halt_loan_until", 0)) - self.s["tick"])}
            try:
                amount = float(amount)
            except (TypeError, ValueError, OverflowError):
                return {"ok": False, "error": "Amount must be a number"}
            if not math.isfinite(amount):
                return {"ok": False, "error": "Amount must be a finite number"}
            if amount <= 0:
                return {"ok": False, "error": "Amount must be greater than 0"}
            if amount > self.loan_limit():
                return {"ok": False, "error": "Exceeds loan headroom: at most %.0f" % self.loan_limit()}
            _sp = self._special()
            _fr = bool(_sp.get("fr"))
            if _fr:
                _used = int(_sp.get("fr_loans", 0))
                if _used >= FR_MAX_LOANS:
                    return {"ok": False,
                            "error": "[Finance Reversal] No loans left this run (%d/%d); refused"
                                     % (_used, FR_MAX_LOANS)}
            # The markup is drawn only at borrow time: it is the price of borrowing, never announced beforehand.
            # [Finance Reversal] off: lower bound +1%%; on: lower bound -20%% (the target may be reduced)
            _lo = FR_LO_BOUND if _fr else LOAN_BUMP_LO_DEFAULT
            pct = random.uniform(_lo, 1.00)
            bump = amount * pct
            _relief = pct < 0
            self.s["target"] = self.s.get("target", TARGET_EQUITY) + bump
            self.s["target_bonus"] = self.s.get("target_bonus", 0.0) + bump
            self.s["loan"]["goal_bumps"].append({
                "amount": round(amount, 2), "pct": round(pct * 100, 2),
                "bump": round(bump, 2), "tick": self.s.get("tick", 0),
                "at": time.time()})
            self.s["balance"] += amount
            self.s["loan"]["balance"] += amount
            self.s["loan"]["borrowed"] += amount
            self.s["loan"]["loans"] += 1
            if _fr:
                _sp["fr_loans"] = int(_sp.get("fr_loans", 0)) + 1
            if _relief:
                # Clean up leftovers from the old random event (the switch now owns the one-time reduction semantics)
                self.s.get("mods", {}).pop("loan_bump_lo", None)
            self._event("[Loan] Borrowed %.0f Tokens (loan %d%s, now owed %.0f); target raised %+.0f (%+.1f%%) -> new target %.0f" % (
                amount, self.s["loan"]["loans"],
                (", Finance Reversal %d/%d" % (_sp.get("fr_loans", 0), FR_MAX_LOANS)) if _fr else "",
                self.s["loan"]["balance"],
                bump, pct * 100, self.s["target"]), "loan")
            # The countdown stops only once held Tokens are back above 0; otherwise it runs to the end.
            # A loan raises cash and debt together and leaves net value unchanged -- it buys margin to keep playing, it does not erase the loss.
            if self.s.get("negative_since") is not None and self.s["balance"] >= 0:
                self.s["negative_since"] = None
                self.s["negative_since_at"] = 0.0
                self.s["negative_notified"] = False
            self._save()
            return {"ok": True, "amount": amount,
                    "pct": round(pct * 100, 2), "bump": round(bump, 2),
                    "new_target": self.s["target"],
                    "warning": "This loan has raised the target by %+.2f%% (current range: %+.1f%%~+100%%). That is the price of borrowing, not free money." % (
                                   pct * 100, (FR_LO_BOUND if _fr else LOAN_BUMP_LO_DEFAULT) * 100),
                    "state": self._state_light()}

    def repay(self, amount=None):
        with LOCK:
            if self.s.get("finished"):
                return {"ok": False, "error": "Session ended"}
            debt = self.s["loan"]["balance"]
            if debt <= 0:
                return {"ok": False, "error": "No debt outstanding"}
            try:
                amount = float(amount) if amount is not None else debt
            except (TypeError, ValueError):
                return {"ok": False, "error": "Amount must be a number"}
            amount = min(amount, debt)
            if self.s["balance"] < amount:
                amount = max(0.0, self.s["balance"])
            if amount <= 0:
                return {"ok": False, "error": "Insufficient available cash"}
            self.s["balance"] -= amount
            self.s["loan"]["balance"] -= amount
            self.s["loan"]["repaid"] += amount
            self._event("[Repay] Repaid %.0f Tokens (remaining debt %.0f)" % (amount, self.s["loan"]["balance"]), "loan")
            self._save()
            return {"ok": True, "amount": amount, "state": self._state_light()}

    def _settle_loan(self):
        debt = self.s["loan"]["balance"]
        if debt <= 0:
            return
        for p in list(self.s["positions"]):
            self.close_position(p["pair"], p["lots"])
        _cash_before = self.s["balance"]
        self.s["balance"] -= debt
        self.s["loan"]["repaid"] += debt
        self.s["loan"]["balance"] = 0.0
        # For report breakdowns: record cash before and after this liquidation so the report shows more than the outcome
        self.s["loan"]["settle"] = {
            "cash_before": round(_cash_before, 2),
            "paid": round(debt, 2),
            "cash_after": round(self.s["balance"], 2),
        }
        self._event("[Loan matured] Forced clearance: repaid %.0f Tokens, account capital %.0f" % (debt, self.s["balance"]), "loan")

    # ---------------- trading ----------------
    def open_position(self, pair, side, lots, leverage):
        with LOCK:
            if self.s.get("finished"):
                return {"ok": False, "error": "Session ended"}
            pair = (pair or "").upper()
            side = (side or "").upper()
            if self.s.get("halt_orders") or self.s["tick"] < self.s.get("halt_until", 0):
                return {"ok": False, "error": "Abnormal market conditions; the platform is rejecting orders for now, please try again later"}
            if pair not in PAIRS:
                return {"ok": False,
                        "error": "Unknown pair: %s (available: %s)"
                                 % (pair, ", ".join(PAIRS.keys()))}
            if side not in ("LONG", "SHORT"):
                return {"ok": False, "error": "Direction must be LONG or SHORT"}
            try:
                lots = float(lots)
                leverage = int(leverage)
            except (TypeError, ValueError, OverflowError):
                return {"ok": False, "error": "Lots/leverage must be numbers"}
            if not math.isfinite(lots) or not math.isfinite(leverage):
                return {"ok": False, "error": "Lots/leverage must be finite numbers"}
            if lots <= 0:
                return {"ok": False, "error": "Lots must be greater than 0"}
            cap = min(MAX_LEVERAGE, int(self._mod("leverage_cap")))
            if not (MIN_LEVERAGE <= leverage <= cap):
                return {"ok": False, "error": "Leverage must be between %d and %d" % (MIN_LEVERAGE, MAX_LEVERAGE)}
            price = self.s["prices"][pair]
            half = self._eff_spread(pair) / 2
            gross = lots * LOTS_SIZE * price
            before = self._account_notional()
            slip = self._slip_rate(before, before + gross, pair)
            fill = price * (1 + half + slip) if side == "LONG" else price * (1 - half - slip)
            notional = lots * LOTS_SIZE * fill
            margin = notional / leverage
            fee = notional * FEE_RATE * self._mod("fee_mult")
            # Free margin must subtract what is already used, or repeated entries stack leverage until it explodes
            used = self._total_margin()
            avail = self.equity() - used
            if margin + fee > avail:
                return {"ok": False,
                        "error": "Insufficient margin: this order needs %.0f, available %.0f (net value %.0f − in use %.0f)"
                                 % (margin + fee, max(0.0, avail), self.equity(), used)}
            self.s["balance"] -= fee
            self.s["total_fees"] += fee
            self.s["order_count"] += 1
            # Keep one position per pair per side: adds merge, lots accumulate, entry price is the lots-weighted average.
            # This keeps the positions table from stacking a dozen identical rows and blocks "infinite re-entry" abuse.
            same = [p for p in self.s["positions"]
                    if p["pair"] == pair and p["side"] == side]
            merged = bool(same)
            if merged:
                cur = same[0]
                tot = cur["lots"] + lots
                cur["entry"] = round((cur["entry"] * cur["lots"] + fill * lots) / tot, 6)
                cur["lots"] = tot
                cur["margin"] = round(cur["margin"] + margin, 2)
                cur["fee"] = round(cur["fee"] + fee, 2)
                ntl = tot * LOTS_SIZE * cur["entry"]
                cur["leverage"] = max(1, int(round(ntl / cur["margin"]))) if cur["margin"] > 0 else leverage
                pos = cur
            else:
                pos = {"pair": pair, "side": side, "lots": lots, "entry": round(fill, 6),
                       "leverage": leverage, "margin": round(margin, 2),
                       "opened_tick": self.s["tick"], "fee": round(fee, 2)}
                self.s["positions"].append(pos)
            self.s.setdefault("trades", []).append({
                "tick": self.s["tick"], "type": "open", "pair": pair, "side": side,
                "lots": lots, "leverage": leverage, "fill": round(fill, 6),
                "notional": round(notional, 2), "margin": round(margin, 2),
                "fee": round(fee, 2), "slip": round(slip, 6),
                "slip_cost": round(gross * slip, 2),
                "spread_cost": round(gross * half, 2)})
            if merged:
                self._event("Added %s %s %.0f lots @%.4f (total %.0f lots, average %.4f, margin used %.0f)" % (
                    pair, side, lots, fill, pos["lots"], pos["entry"], pos["margin"]), "open")
            else:
                self._event("Opened %s %s %.0f lots @%.4f (%d x leverage, margin used %.0f)" % (
                    pair, side, lots, fill, leverage, margin), "open")
            self._save()
            return {"ok": True, "position": pos, "state": self._state_light()}

    def close_position(self, pair, lots=None):
        with LOCK:
            if self.s.get("finished"):
                return {"ok": False, "error": "Session ended"}
            # Exchange maintenance: active closing is blocked; forced liquidation goes through _blowup() and is exempt
            if self.s["tick"] < self.s.get("halt_close_until", 0):
                return {"ok": False,
                        "error": "Exchange maintenance in progress, closing paused (%d ticks left)" % (
                            int(self.s.get("halt_close_until", 0)) - self.s["tick"])}
            pair = (pair or "").upper()
            price = self.s["prices"].get(pair)
            if price is None:
                return {"ok": False,
                        "error": "Unknown pair: %s (available: %s)"
                                 % (pair, ", ".join(PAIRS.keys()))}
            idxs = [i for i, p in enumerate(self.s["positions"]) if p["pair"] == pair]
            if not idxs:
                return {"ok": False, "error": "No position in %s" % pair}
            remaining = float(lots) if lots else None
            closed = []
            # Iterate in reverse and pop at the end to avoid index drift after removals
            for i in sorted(idxs, reverse=True):
                if remaining is not None and remaining <= 0:
                    break
                p = self.s["positions"][i]
                qty = p["lots"] if remaining is None else min(p["lots"], remaining)
                half = self._eff_spread(pair) / 2
                total = self._account_notional()
                slip = self._slip_rate(max(0.0, total - qty * LOTS_SIZE * price), total, pair)
                fill = price * (1 - half - slip) if p["side"] == "LONG" else price * (1 + half + slip)
                pnl = self._position_pnl(p, fill)
                fee = qty * LOTS_SIZE * fill * FEE_RATE * self._mod("fee_mult")
                self.s["balance"] += pnl - fee
                self.s["total_fees"] += fee
                self.s["order_count"] += 1
                if qty >= p["lots"]:
                    self.s["positions"].pop(i)
                else:
                    p["lots"] -= qty
                    p["margin"] = self._position_margin(p)
                closed.append({"pair": pair, "side": p["side"], "lots": qty,
                               "fill": round(fill, 6), "pnl": round(pnl, 2)})
                self.s.setdefault("trades", []).append({
                    "tick": self.s["tick"], "type": "close", "pair": pair, "side": p["side"],
                    "lots": qty, "fill": round(fill, 6), "pnl": round(pnl, 2),
                    "fee": round(fee, 2), "slip": round(slip, 6),
                    "slip_cost": round(qty * LOTS_SIZE * price * slip, 2),
                    "spread_cost": round(qty * LOTS_SIZE * price * half, 2),
                    "entry": p["entry"], "leverage": p["leverage"]})
                self._event("Closed %s %s %.0f lots @%.4f, P&L %+.0f" % (pair, p["side"], qty, fill, pnl), "close")
                if remaining is not None:
                    remaining -= qty
            self._save()
            return {"ok": True, "closed": closed, "state": self._state_light()}

    def close_all(self):
        with LOCK:
            if self.s.get("finished"):
                return {"ok": False, "error": "Session ended"}
            closed = []
            for p in list(self.s["positions"]):
                r = self.close_position(p["pair"], p["lots"])
                if r.get("ok"):
                    closed.extend(r["closed"])
            return {"ok": True, "closed": closed, "state": self._state_light()}

    # ---------------- post-round report ----------------
    def _metrics(self, final_eq=None):
        curve = list(self.s.get("equity_curve", []))
        # Settling happens after the last tick (close + repay), so the final equity must be appended as the curve's last point,
        # or the report misses the final crash -- we once had a curve ending at 920k while the report said -1.29M
        if final_eq is not None and curve:
            if abs(float(curve[-1]["equity"]) - float(final_eq)) > 0.01:
                curve.append({"tick": self.s.get("tick", 0), "equity": round(float(final_eq), 2)})
        eqs = [c["equity"] for c in curve] or [self.equity()]
        peak, mdd = eqs[0], 0.0
        for v in eqs:
            peak = max(peak, v)
            if peak > 0:
                mdd = max(mdd, (peak - v) / peak)
        rets = []
        for i in range(1, len(eqs)):
            if eqs[i - 1] > 0:
                rets.append(eqs[i] / eqs[i - 1] - 1.0)
        sharpe = 0.0
        if len(rets) > 2:
            mu = sum(rets) / len(rets)
            var = sum((x - mu) ** 2 for x in rets) / len(rets)
            sd = var ** 0.5
            if sd > 0:
                sharpe = mu / sd * (540 ** 0.5)
        closes = [t for t in self.s.get("trades", []) if t.get("type") == "close"]
        wins = [t for t in closes if t.get("pnl", 0) > 0]
        gains = [t.get("pnl", 0) for t in closes if t.get("pnl", 0) > 0]
        losses = [t.get("pnl", 0) for t in closes if t.get("pnl", 0) < 0]
        return {
            "curves": curve, "start": eqs[0], "peak": max(eqs), "low": min(eqs),
            "end": eqs[-1], "mdd": mdd, "sharpe": sharpe,
            "trades_n": len(closes), "win_n": len(wins),
            "win_rate": (len(wins) / len(closes)) if closes else 0.0,
            "best": (max(gains) if gains else None),
            "worst": (min(losses) if losses else None),
            "fees": self.s.get("total_fees", 0.0), "swap": self.s.get("total_swap", 0.0),
            "margin_calls": self.s.get("margin_calls", 0),
            "orders": self.s.get("order_count", 0),
            "slip_cost": sum(float(t.get("slip_cost") or 0.0) for t in self.s.get("trades", [])),
            "spread_cost": sum(float(t.get("spread_cost") or 0.0) for t in self.s.get("trades", [])),
            "trades_all": len(self.s.get("trades", [])),
        }

    def _curve_svg(self, curve, w=880, h=300):
        """Equity curve: X axis in minutes, the Y=0 survival line, baselines, key event markers.

        Design notes (all adaptive, no per-run numbers hard-coded):
        - the Y axis fits both the all-time high and the final equity, and the negative range stays fully visible
        - Y=0 is the divide where capital is gone and debt begins, drawn as its own red dashed line
        - initial capital and target as two dashed baselines, so the distance to either is obvious
        - the stretch below the 0 axis is drawn in a deeper red to mark being blown out
        """
        if len(curve) < 2:
            return '<p class="muted">Not enough data to plot the curve.</p>'
        eqs = [float(c["equity"]) for c in curve]
        ticks = [int(c.get("tick") or 0) for c in curve]
        start_eq = float(self.s.get("genesis", STARTER_CASH))
        target_eq = float(self.s.get("target", TARGET_EQUITY))
        n = len(eqs)

        # ---- Y range: include the low / high / 0 / starting capital / target ----
        cand = [min(eqs), max(eqs), 0.0, start_eq]
        if target_eq > start_eq:
            cand.append(target_eq)
        lo, hi = min(cand), max(cand)
        span = (hi - lo) or 1.0
        lo -= span * 0.08
        hi += span * 0.08

        pad_l, pad_r, pad_t, pad_b = 76, 104, 20, 44
        plot_w = w - pad_l - pad_r
        plot_h = h - pad_t - pad_b
        t0, t1 = ticks[0], ticks[-1]
        tspan = (t1 - t0) or 1

        def X(i):
            return pad_l + plot_w * (ticks[i] - t0) / tspan

        def Y(v):
            return pad_t + plot_h - plot_h * (v - lo) / (hi - lo)

        parts = []

        # ---- grid + Y-axis ticks ----
        for k in range(5):
            v = lo + (hi - lo) * k / 4
            gy = Y(v)
            parts.append('<line x1="%d" y1="%.1f" x2="%d" y2="%.1f" stroke="#ececec"/>'
                         % (pad_l, gy, w - pad_r, gy))
            parts.append('<text x="%d" y="%.1f" text-anchor="end" font-size="10" fill="#8a8a8a">%s</text>'
                         % (pad_l - 8, gy + 3.5, "{:,.0f}".format(v)))

        # ---- X axis: minute ticks ----
        total_min = max(1, int(round(tspan * TICK_SECONDS / 60.0)))
        step = 5 if total_min > 20 else (2 if total_min > 8 else 1)
        minute = 0
        while minute <= total_min:
            frac = (minute * 60.0 / TICK_SECONDS) / float(tspan)
            gx = pad_l + plot_w * min(1.0, frac)
            parts.append('<line x1="%.1f" y1="%d" x2="%.1f" y2="%d" stroke="#f4f4f4"/>'
                         % (gx, pad_t, gx, h - pad_b))
            parts.append('<text x="%.1f" y="%d" text-anchor="middle" font-size="10" fill="#9a9a9a">%d′</text>'
                         % (gx, h - pad_b + 15, minute))
            minute += step
        parts.append('<text x="%.1f" y="%d" text-anchor="middle" font-size="10" fill="#b0b0b0">%s</text>'
                     % (pad_l + plot_w / 2.0, h - 6, "Run duration (minutes)"))

        # ---- reference lines: starting capital / target / zero axis ----
        def baseline(v, color, label, dash, width=1.2, op=0.85):
            if not (lo <= v <= hi):
                return ""
            gy = Y(v)
            return ('<line x1="%d" y1="%.1f" x2="%d" y2="%.1f" stroke="%s" stroke-width="%.1f" '
                    'stroke-dasharray="%s" opacity="%.2f"/>'
                    '<text x="%d" y="%.1f" font-size="10" fill="%s" opacity="0.9">%s</text>'
                    % (pad_l, gy, w - pad_r, gy, color, width, dash, op,
                       w - pad_r + 6, gy + 3.5, color, label))

        parts.append(baseline(start_eq, "#0d9458", "Initial capital", "5 4"))
        if target_eq > start_eq:
            parts.append(baseline(target_eq, "#c9971b", "Target to win", "5 4"))
        parts.append(baseline(0.0, "#c62828", "Capital wiped out", "2 3", width=1.4, op=0.95))

        # ---- area fill: light above zero, dark red below ----
        base_y = Y(0.0)

        def area_poly(color, opacity, keep_neg):
            seg = [(X(i), Y(eqs[i])) for i in range(n)
                   if (eqs[i] < 0 if keep_neg else eqs[i] >= 0)]
            if len(seg) < 2:
                return ""
            p = ["%.1f,%.1f" % (seg[0][0], base_y)]
            p += ["%.1f,%.1f" % xy for xy in seg]
            p.append("%.1f,%.1f" % (seg[-1][0], base_y))
            return '<polygon points="%s" fill="%s" opacity="%.2f"/>' % (" ".join(p), color, opacity)

        end_eq = eqs[-1]
        line_color = "#0d9458" if end_eq >= start_eq else "#d93025"
        parts.append(area_poly(line_color, 0.07, False))
        first_neg = next((i for i, v in enumerate(eqs) if v < 0), None)
        if first_neg is not None:
            parts.append(area_poly("#a31515", 0.28, True))

        # ---- polyline: switch to thick dark red after a blow-out ----
        if first_neg is not None and first_neg > 0:
            above = " ".join("%.1f,%.1f" % (X(i), Y(eqs[i])) for i in range(first_neg + 1))
            below = " ".join("%.1f,%.1f" % (X(i), Y(eqs[i])) for i in range(first_neg, n))
            parts.append('<polyline points="%s" fill="none" stroke="%s" stroke-width="1.8"/>'
                         % (above, line_color))
            parts.append('<polyline points="%s" fill="none" stroke="#8b0000" stroke-width="2.3"/>'
                         % below)
        elif first_neg is not None:
            parts.append('<polyline points="%s" fill="none" stroke="#8b0000" stroke-width="2.3"/>'
                         % " ".join("%.1f,%.1f" % (X(i), Y(eqs[i])) for i in range(n)))
        else:
            parts.append('<polyline points="%s" fill="none" stroke="%s" stroke-width="1.8"/>'
                         % (" ".join("%.1f,%.1f" % (X(i), Y(eqs[i])) for i in range(n)), line_color))

        # ---- key event markers (pick points automatically, no hard-coded captions) ----
        marks = []
        if first_neg is not None:
            marks.append((first_neg, "Blown out", "#8b0000"))
        closes = [t for t in self.s.get("trades", []) if t.get("type") == "close"]
        if closes:
            worst = min(closes, key=lambda t: float(t.get("pnl") or 0.0))
            if float(worst.get("pnl") or 0.0) < 0:
                wt = int(worst.get("tick") or 0)
                idx = min(range(n), key=lambda i: abs(ticks[i] - wt))
                far = all(abs(ticks[idx] - ticks[m[0]]) > tspan * 0.02 for m in marks)
                if far:
                    marks.append((idx, "Largest single loss", "#c62828"))

        # Markers hug the curve; labels alternate above and below so they do not overlap
        for mi, (idx, label, color) in enumerate(marks):
            mx, my = X(idx), Y(eqs[idx])
            below = (mi % 2 == 0)
            ty = my + (16 if below else -10)
            anchor = 'middle'
            if mx > w - pad_r - 60:
                anchor = 'end'
                mx_t = mx
            elif mx < pad_l + 60:
                anchor = 'start'
                mx_t = mx
            else:
                mx_t = mx
            parts.append('<line x1="%.1f" y1="%.1f" x2="%.1f" y2="%.1f" stroke="%s" '
                         'stroke-width="1" stroke-dasharray="3 3" opacity="0.55"/>'
                         % (mx, my, mx, ty - (0 if below else 6), color))
            parts.append('<circle cx="%.1f" cy="%.1f" r="3.4" fill="%s" stroke="#fff" stroke-width="1"/>'
                         % (mx, my, color))
            parts.append('<text x="%.1f" y="%.1f" text-anchor="%s" font-size="10" fill="%s" '
                         'font-weight="600">%s</text>' % (mx_t, ty, anchor, color, label))

        return ('<svg viewBox="0 0 %d %d" class="curve" xmlns="http://www.w3.org/2000/svg">%s</svg>'
                % (w, h, "".join(parts)))

    def _manifest_version(self):
        """Report version line: prefer manifest.json, fall back to the internal version number."""
        try:
            for p in (os.path.join(os.path.dirname(self.home), "manifest.json"),
                      os.path.join(self.home, "manifest.json")):
                if os.path.exists(p):
                    with open(p, encoding="utf-8") as fh:
                        return "manifest v%d" % int(json.load(fh).get("version"))
        except Exception:
            pass
        return "Engine internal version %d" % int(self.s.get("version", 0))

    def _write_report(self, reason, final_eq, abnormal=False):
        """Generate the after-action report (HTML only). No exception may disturb gameplay."""
        try:
            import datetime
            import re as _re
            m = self._metrics(final_eq)
            fmt = lambda v: "{:,.2f}".format(v)
            trader = _re.sub(r"[^\w\u4e00-\u9fa5-]", "", self.s.get("trader", "visitor"))[:32] or "visitor"
            now = datetime.datetime.now()
            stamp = now.strftime("%Y%m%d-%H%M%S")
            dur = max(0, int(self._elapsed()))
            target = self.s.get("target", TARGET_EQUITY)
            hit = final_eq >= target and self._qualified()
            if abnormal:
                verdict = "Unsettled (abnormal exit)"
                hit = False
            elif final_eq >= target and not self._qualified():
                verdict = "Target reached but run ineligible"
            else:
                verdict = "Target reached" if hit else "Target missed"
            pnl = final_eq - self.s.get("genesis", STARTER_CASH)
            pnl_pct = pnl / self.s["genesis"] * 100 if self.s.get("genesis") else 0.0
            # Overall rating: return bucket + Sharpe bonus - drawdown penalty.
            # Return alone would hand an S to "one high-leverage gamble" and hide drawdown and volatility.
            _m = self._metrics(final_eq)
            _shp = float(_m.get("sharpe") or 0.0)
            _mdd = float(_m.get("mdd") or 0.0)
            score = (3 if pnl_pct >= 200 else 2 if pnl_pct >= 100
                     else 1 if pnl_pct >= 30 else 0)
            if _shp >= 1.5:
                score += 1          # good return quality
            elif _shp < 0:
                score -= 1          # volatility swamps the return, one notch down
            if _mdd >= 0.5:
                score -= 1          # drawdown over half, one notch down
            ring = ("S" if score >= 4 else "A" if score >= 3
                    else "B" if score >= 2 else "C" if score >= 1 else "D")
            flags = []
            if self.s.get("unnamed"):
                flags.append("Started without the launcher")
            if self.s.get("clock_cheat"):
                flags.append("System clock rolled back")
            if self.s.get("tampered"):
                flags.append("Save file was tampered with")
            flag_txt = " · ".join(flags)

            rows = []
            _all_trades = self.s.get("trades", [])
            for t in _all_trades:
                if t.get("type") == "open":
                    rows.append("<tr><td>%s</td><td>Open</td><td>%s</td><td>%s</td><td>%.0f</td><td>%d×</td><td>%.4f</td><td>%.0f</td><td class=\"muted\">%.0f</td><td>-</td></tr>"% (
                                    t.get("tick"), t.get("pair"), "Long" if t.get("side") == "LONG" else "Short",
                                    t.get("lots", 0), t.get("leverage", 1),
                                    float(t.get("fill") or 0), float(t.get("margin") or 0),
                                    float(t.get("fee") or 0)))
                else:
                    cls = "up" if t.get("pnl", 0) >= 0 else "down"
                    rows.append("<tr><td>%s</td><td>Close</td><td>%s</td><td>%s</td><td>%.0f</td><td class=\"muted\">—</td><td>%.4f</td><td class=\"muted\">—</td><td class=\"muted\">%.0f</td><td class=\"%s\">%+.0f</td></tr>" % (
                                    t.get("tick"), t.get("pair"), "Long" if t.get("side") == "LONG" else "Short",
                                    t.get("lots", 0), float(t.get("fill") or 0),
                                    float(t.get("fee") or 0), cls, t.get("pnl", 0)))

            ev_rows = []
            _KIND_CN = {"gap": "Gap", "loan": "Loan", "margin_call": "Margin call",
                        "blowup": "Blown out", "end": "Settle", "open": "Open position",
                        "close": "Close position", "warn": "Warning", "ok": "Event", "info": "Info",
                        "stopout": "Forced liquidation", "news": "Event"}
            for e in self.s.get("events", []):
                _k = e.get("kind") or "info"
                ev_rows.append('<li class="ev-%s"><span class="tag">%s</span> '
                               '<span class="evt">t%s</span> %s</li>' % (
                                   _k, _KIND_CN.get(_k, _k),
                                   e.get("tick", "—"), e.get("text", "")))

            # ---------- loan ledger breakdown ----------
            _loan = self.s.get("loan") or {}
            _borrowed = float(_loan.get("borrowed") or 0.0)
            _repaid = float(_loan.get("repaid") or 0.0)
            _lint = float(_loan.get("interest") or 0.0)
            _ldebt = float(_loan.get("balance") or 0.0)
            _lset = _loan.get("settle") or {}
            if _borrowed > 0:
                _rows_loan = []
                _rows_loan.append('<div class="kv"><span>Total borrowed</span><span>%s</span></div>' % fmt(_borrowed))
                _rows_loan.append('<div class="kv"><span>Total repaid</span><span>%s</span></div>' % fmt(_repaid))
                _rows_loan.append('<div class="kv"><span>└ of which interest</span><span>%s</span></div>' % fmt(_lint))
                if _lset:
                    _rows_loan.append('<div class="kv"><span>Cash before settlement</span><span>%s</span></div>' % fmt(_lset.get("cash_before", 0)))
                    _rows_loan.append('<div class="kv"><span>Settlement repayment</span><span>%s</span></div>' % fmt(_lset.get("paid", 0)))
                    _rows_loan.append('<div class="kv"><span>Cash after settlement</span><span>%s</span></div>' % fmt(_lset.get("cash_after", 0)))
                _rows_loan.append('<div class="kv"><span>Current debt</span><span>%s</span></div>' % fmt(_ldebt))
                _bumps = _loan.get("goal_bumps") or []
                if _bumps:
                    _rows_loan.append(
                        "<div class=\"kv\" style=\"grid-column:1/-1\"><span>Loan by loan (target raised)</span><span>%s</span></div>" % " ｜ ".join(
                            "t%s loan %s (%+.1f%% -> %+.0f)" % (
                                b.get("tick", "—"), fmt(b.get("amount", 0)),
                                float(b.get("pct") or 0), float(b.get("bump") or 0))
                            for b in _bumps))
                _loan_block = ("<section id=\"p4\"><h2>Loan ledger</h2><div class=\"kvbox\">%s</div><div class=\"note\">Net value = cash − debt. Borrowing raises cash and debt together, so net value does not change; at settlement cash is reduced by the debt, the debt goes to zero, and net value still does not change.</div></section>"
                               % "".join(_rows_loan))
            else:
                # Keep the block even with no loans so readers see explicitly that this round had none
                _loan_block = ("<section id=\"p4\"><h2>Loan ledger</h2><div class=\"kvbox\"><div class=\"kv\"><span>No loans this run</span><span>—</span></div></div></section>")
            _sc = self.scratch_read()
            _sc_rows = []
            for _x in _sc:
                _sc_rows.append('<div class="sc-item"><span class="sc-meta">t%s · %s</span>%s</div>'
                                % (_x.get("tick", "—"),
                                   ("%.0f s" % float(_x.get("elapsed") or 0)),
                                   str(_x.get("text", "")).replace("<", "&lt;").replace(">", "&gt;")))
            _d = self.s.get("difficulty") or {}
            _dl_gap = _dl_liq = ""
            if _d:
                try:
                    _gp = float(_d.get("gap_pct") or GAP_LEVELS[int(_d["gap"])][1])
                    _ld = float(_d.get("liq_depth") or LIQ_LEVELS[int(_d["liq"])][1])
                    _dl_gap = "%s（%.2f%%/tick）" % (GAP_LEVELS[int(_d["gap"])][0], _gp * 100)
                    _dl_liq = "%s (depth %.1fM)" % (LIQ_LEVELS[int(_d["liq"])][0], _ld / 1000000.0)
                except Exception:
                    _dl_gap = _dl_liq = ""
            # Fast-forward usage
            _ffr = [int(x) for x in (self.s.get("ff_records") or [])]
            _ff_used = float(self.s.get("ff_used") or 0.0)
            _ff_parts = []
            _i = 0
            while _i < len(_ffr):
                _v = _ffr[_i]
                _n = 1
                while _i + _n < len(_ffr) and _ffr[_i + _n] == _v:
                    _n += 1
                _ff_parts.append("%d′%02d″%s" % (
                    _v // 60, _v % 60, ("×%d" % _n) if _n > 1 else ""))
                _i += _n
            _ff_txt = (" + ".join(_ff_parts) if _ff_parts else "Unused")
            # ---------- cost attribution: split net PnL into five verifiable parts ----------
            _slip_c = float(m.get("slip_cost") or 0.0)
            _spread_c = float(m.get("spread_cost") or 0.0)
            _fees_c = float(m.get("fees") or 0.0)
            _swap_c = float(m.get("swap") or 0.0)
            _slot_win = float((self.s.get("special") or {}).get("slot_win") or 0.0)
            _gross = float(pnl) + _slip_c + _spread_c + _fees_c + _swap_c - _slot_win
            _attr_rows = [
                ("Direction and gaps (gross P&L)", _gross, ""),
                ("└ Slippage cost", -_slip_c, "down" if _slip_c > 0 else ""),
                ("└ Spread cost", -_spread_c, "down" if _spread_c > 0 else ""),
                ("└ Commission", -_fees_c, "down" if _fees_c > 0 else ""),
                ("└ Overnight interest", -_swap_c, "down" if _swap_c > 0 else ""),
                ("Slot Machine payouts", _slot_win, "up" if _slot_win > 0 else ""),
                ("Net P&L", float(pnl), "up" if pnl >= 0 else "down"),
            ]
            _attr_html = "".join(
                '<div class="kv"><span>%s</span><span class="%s">%s</span></div>'
                % (k, c, fmt(v)) for k, v, c in _attr_rows)

            _as_items = self.s.get("assist") or []
            _as_rows = []
            for _x in _as_items:
                _who = _x.get("who")
                if _who == "ai":
                    _tag, _cls = "Contestant", "as-ai"
                elif _who == "human":
                    _tag, _cls = "Spectators", "as-human"
                else:
                    _tag, _cls = "System", "as-sys"
                _as_rows.append(
                    '<div class="asline %s"><span class="astag">[t%s] %s</span> %s</div>'
                    % (_cls, _x.get("tick", 0), _tag,
                       str(_x.get("text") or "").replace("<", "&lt;").replace(">", "&gt;")))
            body = {
                "trader": trader,
                "ff_used": "%s seconds" % fmt(_ff_used),
                "ff_remain": "%s seconds" % fmt(max(0.0, FF_TOTAL_SECONDS - _ff_used)),
                "ff_records": _ff_txt,
                "ff_count": str(len(_ffr)),
                "mode": "Random events on" if self.s.get("events_on", True) else "Ideal case",
                "flagline": ("<div class=\"sub\" style=\"color:#d93025;font-weight:600\">⚠ %s</div>" % flag_txt) if flag_txt else "",
                "diffline": ("<div class=\"sub\" style=\"color:#0b6bcb;font-weight:600\">This run's difficulty · Black Swan frequency: %s | liquidity drought: %s</div>" % (
                    _dl_gap, _dl_liq)) if (_dl_gap and _dl_liq) else "",
                "gap_lv": _dl_gap or "—",
                "liq_lv": _dl_liq or "—",
                "flagmd": (("- ⚠ Violation flag: %s" % flag_txt) + chr(10)) if flag_txt else "",
                "verdict": verdict,
                "hitcls": "hit" if hit else "miss",
                "now": now.strftime("%Y-%m-%d %H:%M:%S"),
                "dur": "%d min %d s" % (dur // 60, dur % 60),
                "reason": reason,
                "finaleq": fmt(final_eq),
                "target": fmt(target),
                "pnl": fmt(pnl),
                "pnlcls": "up" if pnl >= 0 else "down",
                "pnlpct": "%+.2f" % pnl_pct,
                "ring": ring,
                "svg": self._curve_svg(m["curves"]),
                "mdd": "%.2f" % (m["mdd"] * 100),
                "sharpe": "%.2f" % m["sharpe"],
                "trades_n": str(m["trades_n"]),
                "trades_all": str(m.get("trades_all", 0)),
                "verline": "Tokens Trading Market · %s · This report is generated automatically" % self._manifest_version(),
                "seedline": "Random seed %s · reproduce with: TM_SEED=%s and start a new run" % (
                    self.s.get("seed") or "—", self.s.get("seed") or "—"),
                "winrate": "%.1f" % (m["win_rate"] * 100),
                "best": fmt(m["best"]) if m["best"] is not None else "—",
                "worst": fmt(m["worst"]) if m["worst"] is not None else "—",
                "fees": fmt(m["fees"]),
                "swap": fmt(m["swap"]),
                "mcall": str(m["margin_calls"]),
        "abn": str(int(self.s.get("abnormal_exits", 0))),
                "borrowed_txt": fmt(self.s["loan"]["borrowed"]),
                "rows": "".join(rows) or '<tr><td colspan="10" class="muted">No trades</td></tr>',
                "loanblock": _loan_block,
                "scrows": "".join(_sc_rows) or '<div class="muted">No content</div>',
                "asrows": "".join(_as_rows) or '<div class="muted">not used this match</div>',
                "asn": str(len(_as_items)),
                "scn": str(len(_sc)),
                "evrows": "".join(ev_rows) or '<li class="muted">No key events</li>',
                "attrib": _attr_html,
            }

            html = """<!DOCTYPE html>
<html lang="en"><head><meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>After-action report - {trader} - {now}</title>
<style>
:root{{--bg:#f6f7f9;--card:#fff;--line:#e4e6eb;--ink:#1d2129;--muted:#86909c;--up:#0d9458;--down:#d93025}}
*{{box-sizing:border-box}}
body{{margin:0;background:var(--bg);color:var(--ink);font:14px/1.65 -apple-system,"Segoe UI","Microsoft YaHei",sans-serif}}
.wrap{{max-width:980px;margin:0 auto;padding:28px 20px 60px}}
header{{border-top:6px solid #c8161d;background:var(--card);border-radius:10px;padding:22px 26px;margin-bottom:18px;box-shadow:0 1px 3px rgba(0,0,0,.06)}}
h1{{margin:0 0 4px;font-size:22px;letter-spacing:-.3px}}
.sub{{color:var(--muted);font-size:13px}}
.badge{{display:inline-block;margin-left:10px;padding:2px 10px;border-radius:999px;font-size:12px;font-weight:600}}
.badge.hit{{background:#e6f6ee;color:var(--up)}}
.badge.miss{{background:#fdecea;color:var(--down)}}
.cards{{display:grid;grid-template-columns:repeat(4,1fr);gap:12px;margin-bottom:18px}}
.card{{background:var(--card);border:1px solid var(--line);border-radius:10px;padding:14px 16px}}
.card .k{{color:var(--muted);font-size:12px;margin-bottom:6px}}
.card .v{{font-size:20px;font-weight:700;font-variant-numeric:tabular-nums}}
.up{{color:var(--up)}} .down{{color:var(--down)}}
section{{background:var(--card);border:1px solid var(--line);border-radius:10px;padding:18px 20px;margin-bottom:18px}}
h2{{margin:0 0 14px;font-size:15px;font-weight:700}}
.curve{{width:100%;height:auto;display:block}}
.grid2{{display:grid;grid-template-columns:repeat(3,1fr);gap:10px}}
.kv{{display:flex;flex-direction:column;gap:3px;padding:9px 12px;border:1px solid var(--line);border-radius:8px}}
.kv span:first-child{{color:var(--muted);font-size:12px}}
.kv span:last-child{{font-weight:600;font-variant-numeric:tabular-nums}}
table{{width:100%;border-collapse:collapse;font-size:12.5px}}
th,td{{padding:6px 8px;text-align:right;border-bottom:1px solid var(--line);font-variant-numeric:tabular-nums}}
th{{color:var(--muted);font-weight:600}}
th:first-child,td:first-child,th:nth-child(2),td:nth-child(2),th:nth-child(3),td:nth-child(3){{text-align:left}}
ul.ev{{list-style:none;padding:0;margin:0;font-size:12.5px;max-height:320px;overflow:auto}}
ul.ev li{{padding:4px 0;border-bottom:1px solid #f2f3f5}}
.tag{{display:inline-block;min-width:70px;font-size:11px;color:var(--muted)}}
.muted{{color:var(--muted)}}
footer{{text-align:center;color:var(--muted);font-size:12px;padding-top:8px}}
.kvbox{{display:grid;grid-template-columns:repeat(auto-fill,minmax(220px,1fr));gap:2px 24px;background:#fbfbfd;border:1px solid var(--line);border-radius:8px;padding:12px 16px;margin-bottom:10px}}
.note{{color:var(--muted);font-size:12.5px;line-height:1.7;padding:0 2px}}
.toc{{display:flex;flex-wrap:wrap;gap:6px 14px;margin:-6px 0 16px;padding:10px 16px;
background:var(--card);border:1px solid var(--line);border-radius:8px;font-size:12.5px}}
.toc a{{color:#0b6bcb;text-decoration:none}}
.toc a:hover{{text-decoration:underline}}
.scratch{{background:#fbfbfd;border:1px solid var(--line);border-radius:8px;padding:10px 14px;max-height:520px;overflow:auto;font-family:-apple-system,"Segoe UI","Microsoft YaHei",sans-serif;font-size:13.5px;line-height:1.75}}
.sc-item{{padding:6px 0;border-bottom:1px dashed #eceef2;white-space:pre-wrap;word-break:break-word}}
.sc-item:last-child{{border-bottom:0}}
.asline{{padding:6px 0;border-bottom:1px dashed #eceef2;white-space:pre-wrap;word-break:break-word}}
.asline:last-child{{border-bottom:0}}
.astag{{font-weight:600;margin-right:6px}}
.as-ai .astag{{color:#0078d4}}
.as-human .astag{{color:#0a7a3d}}
.as-sys .astag{{color:#6b6b6b}}
.sc-meta{{color:var(--muted);margin-right:10px;font-size:12px}}
.ev .tag{{display:inline-block;padding:0 6px;border-radius:4px;background:#eef2f7;color:#5b6b7c;font-size:12px;margin-right:6px}}
.ev .evt{{color:var(--muted);font-size:12px;margin-right:8px}}
</style></head><body><div class="wrap">
<header>
  <h1>Tokens Trading Market · After-action report<span class="badge {hitcls}">{verdict}</span></h1>
  <div class="sub">Player {trader} ({mode}) · duration {dur} · ended because {reason} · generated {now}</div>
  <div class="sub">{seedline}</div>
  {diffline}
  {flagline}
</header>
<nav class="toc">
  <a href="#p1">Key metrics</a><a href="#p2">Cost attribution</a><a href="#p3">Trade details</a>
  <a href="#p4">Loan ledger</a><a href="#p5">Scratchpad</a><a href="#p7">Outside Mercy</a><a href="#p6">Key events</a>
</nav>
<div class="cards">
  <div class="card"><div class="k">Final equity</div><div class="v">{finaleq}</div></div>
  <div class="card"><div class="k">P&L</div><div class="v {pnlcls}">{pnl} ({pnlpct}%)</div></div>
  <div class="card"><div class="k">Target</div><div class="v">{target}</div></div>
  <div class="card"><div class="k">Rating</div><div class="v">{ring}</div></div>
</div>
<section><h2>Equity curve</h2>{svg}</section>
<section id="p1"><h2>Key metrics</h2><div class="grid2">
  <div class="kv"><span>Black Swan frequency</span><span>{gap_lv}</span></div>
  <div class="kv"><span>Liquidity drought</span><span>{liq_lv}</span></div>
  <div class="kv"><span>Fast-forward use</span><span>{ff_records} ({ff_count} times, {ff_used})</span></div>
  <div class="kv"><span>Fast-forward quota left</span><span>{ff_remain}</span></div>
  <div class="kv"><span>Max drawdown</span><span>{mdd}%</span></div>
  <div class="kv"><span>Sharpe ratio</span><span>{sharpe}</span></div>
  <div class="kv"><span>Closed positions</span><span>{trades_n}</span></div>
  <div class="kv"><span>Orders (incl. opens)</span><span>{trades_all}</span></div>
  <div class="kv"><span>Win rate</span><span>{winrate}%</span></div>
  <div class="kv"><span>Largest single win</span><span class="up">{best}</span></div>
  <div class="kv"><span>Largest single loss</span><span class="down">{worst}</span></div>
  <div class="kv"><span>Total commission</span><span>{fees}</span></div>
  <div class="kv"><span>Overnight interest</span><span>{swap}</span></div>
  <div class="kv"><span>Margin calls</span><span>{mcall} times</span></div>
  <div class="kv"><span>Abnormal exits</span><span>{abn} times</span></div>
  <div class="kv"><span>Total borrowed</span><span>{borrowed_txt}</span></div>
</div></section>
<section id="p2"><h2>Cost attribution</h2><div class="kvbox">{attrib}</div>
<div class="note">Net P&L = gross P&L − slippage − spread − commission − overnight interest + Slot Machine payouts. Gross P&L covers direction calls and gap shocks: what you should have made or lost if costs did not exist.</div></section>
<section id="p3"><h2>Trade details ({rowsn} rows)</h2>
<table><thead><tr><th>tick</th><th>Action</th><th>Pair</th><th>Direction</th><th>Lots</th><th>Leverage</th><th>Fill price</th><th>Margin</th><th>Commission</th><th>P&L</th></tr></thead>
<tbody>{rows}</tbody></table></section>
{loanblock}
<section id="p5"><h2>Scratchpad ({scn} entries)</h2><div class="scratch">{scrows}</div></section>
<section id="p7"><h2>Outside Mercy ({asn} entries)</h2><div class="scratch">{asrows}</div></section>
<section id="p6"><h2>Key events</h2><ul class="ev">{evrows}</ul></section>
<footer>{verline}</footer>
</div></body></html>""".format(rowsn=len(rows), **body)

            outdir = os.path.join(self.home, "reports")
            os.makedirs(outdir, exist_ok=True)
            base = "%s_%s" % (stamp, trader)
            hp = os.path.join(outdir, base + ".html")
            with open(hp, "w", encoding="utf-8") as f:
                f.write(html)
            return hp
        except Exception as exc:
            # Silent failures once meant "no report and nobody knew"; leave a trace here that can be checked
            try:
                import traceback
                _log = os.path.join(self.home, "reports", ".last_error.txt")
                os.makedirs(os.path.dirname(_log), exist_ok=True)
                with open(_log, "a", encoding="utf-8") as fh:
                    fh.write(("[%s] %s" + chr(10) + "%s" + chr(10) + chr(10)) % (
                        now.strftime("%Y-%m-%d %H:%M:%S"), exc, traceback.format_exc()))
            except Exception:
                pass
            return None

    def abnormal_exit_report(self, reason="Abnormal exit"):
        """On "end the process" / Task Manager kill, leave a snapshot report.

        Positions are not settled and finished is not set; the current state is just written into reports/
        so the player can later see exactly how the run broke off.
        """
        with LOCK:
            eq = self.equity()
            self.s["abnormal_exits"] = int(self.s.get("abnormal_exits", 0)) + 1
            self._event("[Abnormal exit] %s: not settled, snapshot report written" % reason, "warn")
            self._save()
            return self._write_report(reason, eq, abnormal=True)

    def quit_session(self):
        with LOCK:
            if self.s.get("finished"):
                return {"ok": False, "error": "This run is over; use /reset to start a new one"}
            return self._end_session("Ended voluntarily")

    def reset(self, count=True):
        with LOCK:
            now = time.time()
            if count:
                last = self.s.get("last_reset_at", 0.0)
                wait = RESET_COOLDOWN - (now - last)
                if last and wait > 0:
                    return {"ok": False, "error": "Restarting too often; wait %.0f seconds" % wait,
                            "state": self._state_light()}
            trader = self.s.get("trader", "Guest")
            n = self.s.get("resets", 0) + (1 if count else 0)
            self.s = _new_session()
            self.s["trader"] = trader
            self.s["resets"] = n
            self.s["last_reset_at"] = now
            self._elapsed_watch = 0.0          # reset this too
            _purge_data_dir(self.home)         # clear everything under data/ except reports/
            self._save()
            purge_agent_dir(self.home)
            return {"ok": True, "state": self._state_light(), "resets": n}

    # ---------------- views ----------------
    def _state_light(self):
        """Reply payload for action endpoints: drop the history curve and event feed, keep only the fields needed to judge the situation.

        In full state, price_history (up to 2000x7) and events (60 entries) grow with the run;
        echoing them on every order just burns model context.
        """
        return self.state(include_history=False, include_events=False)

    def state(self, include_history=True, include_events=True):
        with LOCK:
            px = self.s["prices"]
            positions = []
            for p in self.s["positions"]:
                positions.append({
                    "pair": p["pair"], "name": PAIR_NAMES[p["pair"]],
                    "side": p["side"], "lots": p["lots"], "entry": p["entry"],
                    "price": px[p["pair"]], "leverage": p["leverage"],
                    "margin": round(self._position_margin(p), 2),
                    "upnl": round(self._position_pnl(p, px[p["pair"]]), 2),
                    "move_pct": round((px[p["pair"]] / p["entry"] - 1) * 100, 3),
                })
            eq = self.equity()
            ml = self.margin_level()
            target = self.s["target"]
            return {
                "tick": self.s["tick"],
                "session_id": self.s.get("session_id", ""),
                "abnormal_exits": int(self.s.get("abnormal_exits", 0)),
                "paused": bool(self.s.get("paused")),
                "ff": self.ff_plan(),
                "loan_pool_event": (lambda _m: (
                    _m[2] if len(_m) > 2 and self.s["tick"] < _m[1] else ""
                ))((self.s.get("mods") or {}).get("loan_pool_mult") or [None, 0, ""]),
                "closed_n": len([x for x in self.s.get("trades", []) if x.get("type") == "close"]),
                "win_n": len([x for x in self.s.get("trades", [])
                              if x.get("type") == "close" and float(x.get("pnl") or 0) > 0]),
                "fees": round(float(self.s.get("total_fees") or 0), 2),
                "swap": round(float(self.s.get("total_swap") or 0), 2),
                "roll_left": self.roll_state().get("roll_left", 0.0),
                "rolled": bool(self.s.get("difficulty")),
                "difficulty": (self.s.get("difficulty") or None),
                "gap_level": (GAP_LEVELS[int(self.s["difficulty"]["gap"])][0]
                              if self.s.get("difficulty") else ""),
                "liq_level": (LIQ_LEVELS[int(self.s["difficulty"]["liq"])][0]
                              if self.s.get("difficulty") else ""),
                "trader": self.s["trader"],
                "last_ua": self.s.get("last_ua", "")[:80],
                "balance": round(self.s["balance"], 2),
                "equity": round(eq, 2),
                "genesis": self.s["genesis"],
                "pnl": round(eq - self.s["genesis"], 2),
                "pnl_pct": round((eq / self.s["genesis"] - 1) * 100, 2),
                "target": round(target, 2),
                "target_pct": round(eq / target * 100, 2),
                "target_bonus": round(self.s.get("target_bonus", 0.0), 2),
                "base_target": TARGET_EQUITY,
                "margin_level": round(ml * 100, 2) if ml is not None else None,
                "active_mods": [
                    # Show the triggering event's name first (e.g. central-bank easing), fall back to the modifier text only when there is no source
                    (v[2] if len(v) > 2 and v[2] else
                     {"spread_mult": "spread x%.1f" % v[0],
                      "vol_mult": "volatility x%.1f" % v[0],
                      "margin_mult": "margin x%.1f" % v[0],
                      "fee_mult": "commission x%.1f" % v[0],
                      "swap_mult": "interest x%.1f" % v[0],
                      "slip_add": "slippage +%.2f%%" % (v[0] * 100),
                      "leverage_cap": "leverage cap %d" % int(v[0]),
                      "loan_pool_mult": "loan pool x%.2f" % v[0],
                      "gap_mult": "gap x%.1f" % v[0]}.get(k, k))
                    for k, v in (self.s.get("mods") or {}).items() if self.s["tick"] < v[1]
                ][:4],
                "liquidity": {sym: round(self._liquidity(sym) / max(1.0, self._liq_base()), 3) for sym in PAIRS},
                "total_borrowed": round(self.s["loan"]["borrowed"], 2),
                # [Finance Reversal] seconds left (wall clock, GUI refreshes per second); None when inactive
                "loan_bump_remain": self._loan_bump_remain(),
                # Current loan-markup range in percent [low, high]; normally [1, 100], during Finance Reversal [-20, 100]
                "loan_bump_range": [
                    round((FR_LO_BOUND if (self.s.get("special") or {}).get("fr")
                           else LOAN_BUMP_LO_DEFAULT) * 100, 2), 100.0],
                "negative_remain": (
                    max(0.0, NEGATIVE_GRACE * TICK_SECONDS
                        - (time.time() - float(self.s.get("negative_since_at") or time.time())))
                    if self.s.get("negative_since") is not None
                    and self.s["balance"] < 0 else None),
                "margin_call_remain": (
                    max(0, MARGIN_CALL_GRACE - (self.s["tick"] - self.s["margin_call_at"]))
                    if self.s.get("margin_call_at") is not None and self.s["positions"] else None),
                "margin_used": round(self._total_margin(), 2),
                "tampered": bool(self.s.get("tampered")),
                "resets": self.s.get("resets", 0),
                "max_drawdown": round(self._metrics()["mdd"] * 100, 2),
                "sharpe": round(self._metrics()["sharpe"], 2),
                "positions": positions,
                "prices": {s: {"price": px[s], "name": PAIR_NAMES[s],
                               "spread_pct": PAIRS[s]["spread"] * 100} for s in PAIRS},
                "loan": {
                    "balance": round(self.s["loan"]["balance"], 2),
                    "borrowed": round(self.s["loan"]["borrowed"], 2),
                    "interest": round(self.s["loan"]["interest"], 2),
                    "loans": self.s["loan"]["loans"],
                    "goal_bumps": self.s["loan"].get("goal_bumps", []),
                    "limit": round(max(0.0, LOAN_POOL * self._mod("loan_pool_mult")
                                       - self.s["loan"]["balance"]), 2),
                    "rate_pct": LOAN_RATE_PER_TICK * 100,
                },
                "special": self.special_state(),
                "seed": self.s.get("seed"),
                "blowups": self.s["blowups"],
                "margin_calls": self.s["margin_calls"],
                "total_fees": round(self.s["total_fees"], 2),
                "total_swap": round(self.s["total_swap"], 2),
                "order_count": self.s["order_count"],
                "equity_curve": self.s["equity_curve"][-HISTORY_LEN:],
                "price_history": (self.s["price_history"] if include_history else {}),
                "events": (self.s["events"][-60:] if include_events else []),
                "finished": self.s["finished"],
                "session_minutes": SESSION_MINUTES,
                "elapsed_seconds": int(self._elapsed()),
                "unnamed": bool(self.s.get("unnamed")),
                "events_on": bool(self.s.get("events_on", True)),
                "clock_cheat": bool(self.s.get("clock_cheat")),
                "disqualified": not self._qualified(),
            }

    def rules(self):
        return {
            "Name": "Tokens Trading Market",
            "Currency unit": "Tokens",
            "Initial capital": STARTER_CASH,
            "Target": "Reach equity of %.0f Tokens (each loan raises the target by a random 1%%~100%% of that amount)" % TARGET_EQUITY,
            "Lots": "1 lot = %.0f units of base currency" % LOTS_SIZE,
            "Finance Reversal": ("Run-wide switch (not a random event): once on, the run allows up to %d loans and the target uplift range widens from +1%%~+100%% to -20%%~+100%% (the target may be reduced); free at start, enabling mid-run costs %.0f cash" % (FR_MAX_LOANS, SPECIAL_FEE)
                        ).replace("%%", "%"),
            "Slot Machine": ("Run-wide switch: once on, %d plays per run, each 1~%.0f and never above current equity; 80%% nothing / 15%% 5x / 5%% 10x (expected return 1.25x); the payout goes to cash while the target rises by -5%%~100%% of that payout (worst case the target doubles); free at start, enabling mid-run costs %.0f cash" % (
                           SLOT_MAX_PLAYS, SLOT_MAX_STAKE, SPECIAL_FEE)
                       ).replace("%%", "%"),
            "Leverage": "Selectable %d - %d x" % (MIN_LEVERAGE, MAX_LEVERAGE),
            "Spread": {s: "%.3f%%" % (cfg["spread"] * 100) for s, cfg in PAIRS.items()},
            "Overnight interest": {s: "%.4f%%/tick" % (cfg["swap"] * 100) for s, cfg in PAIRS.items()},
            "Margin level": "net value / used margin x 100%%, < %.0f%% margin call, < %.0f%% forced liquidation" % (
                MARGIN_CALL_RATIO * 100, STOP_OUT_RATIO * 100),
            "Slippage": "rises linearly with notional (about %.2f%% at %.0fM notional, cap %.1f%%)" % (
                LIQUIDITY / 1000000.0, SLIP_K * 100, SLIP_MAX * 100),
            "Liquidity drought": "on a tick where a pair gaps, that pair's spread widens %.0f times" % GAP_SPREAD_MULT,
            "Black Swan": "per tick, %.1f%% chance of a %.0f%%-%.0f%% gap" % (GAP_CHANCE * 100, GAP_MIN * 100, GAP_MAX * 100),
            "Commission": "%.3f%% of notional per order" % (FEE_RATE * 100),
            "Loan": "Loan pool %.0f Tokens (may be temporarily scaled by \"Credit crunch / Central bank easing\"); interest %.2f%%/tick (%s); each loan: total target = old target + loan amount × random ratio (1%%~100%%, decided once borrowed)" % (
                LOAN_POOL, LOAN_RATE_PER_TICK * 100, "Borrow and repay at will; forced clearance at maturity"),
            "Session length": "%d minutes" % SESSION_MINUTES,
            "tick interval": "%d seconds" % TICK_SECONDS,
            "Pair": {s: PAIR_NAMES[s] for s in PAIRS},
        }
