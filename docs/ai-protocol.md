# Agent Integration Protocol

The HTTP interface is designed for **one thing: letting a large model understand the board in as
few tokens as possible and make a decision**.

> **What counts as a bug report**: the API contradicting this document, self-contradictory
> numbers, a crash, or visibly corrupted data. Everything else — the difficulty draw, borrowing,
> cutting a loss, the slot machine — is decided inside the game by whoever is playing.

> **Note on language**: in this source edition, runtime messages returned by the API
> (errors, event text, report) are in Chinese. Examples below keep the original Chinese strings
> so you can match what you actually receive.

## 0. Before you start: hard rules

### Requirements

1. **`GET /rules` + `GET /state` are enough**: those two responses carry the settlement rules,
   the fee table, the event table and the full endpoint list.
   This file and the other volumes under `docs/` are the complete manual for **humans**,
   not required reading before a match; following `AGENTS.md` means never opening a Markdown
   file mid-match.
2. **Use Python 3.14, and start with the spectator window open.**
   - Python **3.14 only** (any install location: `run.py` validates the version, not the path).
     `run.py` checks the version first; a wrong version exits with code 2 and prints guidance.
     Do not hunt for 3.10-3.13 or `python3` — the GUI widgets and the `.pyc` files are built for 3.14.
     Every `python` in the commands below means your own 3.14 path.
   - The start command is `run.py`, and a human has to be able to watch your equity, positions and
     event feed live. `run.py` and `run.py server` both open the read-only spectator;
     "use server to skip the window" does not exist. Double-clicking `launchers\Start Match.bat` adds a
     5-second mis-click guard (press `Y` to start). `launchers\AI Start.bat` starts with no prompt and is what
     scripts / agents should use; a cmd-invoked `launchers\Start Match.bat` still counts as human.
   - `--headless` is the only windowless mode, allowed only where there is genuinely no desktop
     (CI, containers, pure SSH). It is forbidden for a local match.
   - If you closed the window by accident, attach again with `launchers\Spectator.bat` (or
     `python run.py spectator`) — it changes nothing: no second server, no second seal.
3. Get information and place orders **only through the HTTP interface**.

### Forbidden

- **Read the sources before the match.** Do not open `src/tm_engine.py`, `src/tm_api.py`,
  `src/tm_watch_ai.py` or `run.py` before the match starts to look up parameters, probabilities,
  the event pool or formulas. That is copying the answers, and every judgement you make afterwards
  stops meaning anything.
- **Use the sources to predict events.** Do not take constants out of the code to work out
  "when the next gap will hit" or "which event will fire", and do not write a script that
  reproduces the engine's internals so you know outcomes in advance.
- **Modify code or data.** Do not edit any source file, do not read or write `src/data/session.json`
  directly, do not patch the save file to get around the API.
- **Use outside information.** Do not look up this project's past matches, other players' results,
  or community discussion to build a strategy.

### Allowed

- Once the match has started you may write code, build models, compute expectations, run a Monte
  Carlo, fit distributions — **as long as your inputs come from the game's API** (`/rules`,
  `/state`, `/prices`, the event feed). Analytical skill is part of what this environment tests.
- Write your reasoning into the scratchpad; it is preserved alongside the report.

### The guard will actually catch you

The moment a match starts, **`run.py` seals the three modules that carry game parameters** —
`src/tm_engine.py`, `src/tm_api.py`, `src/scratchpad.py`. They are encrypted with a one-off key and
written outside the project (`%LOCALAPPDATA%\TokensMarketGuard\<random>\`); decoys take their place
in `src/`. `tm_watch_ai.py` stays readable on purpose: it is the spectator UI, it talks to `/state`
over HTTP and never imports the engine, so it leaks nothing and keeping it readable lets a second
spectator window attach to a running match.

A crashed match leaves the vault behind; the next `python run.py` restores it automatically before
loading anything. What you read will be:

```
#  CHEATING DETECTED
#  This file is a decoy. The real sources are sealed while a match is running.
```

If you go further and execute or `import` a decoy, it drops a cheat flag and the guard immediately:

1. sends `POST /shutdown` — **the match is terminated**
2. prints `CHEATING DETECTED`
3. leaves `_guard_vault/CHEAT_FLAG` for the referee to inspect

The guard restores the sources and exits when the match ends. So: **do not touch the sources** —
that ends your run.

### Why

This environment measures **decision-making under incomplete information and real friction**.
Mining the API's data for patterns and computing probabilities is a skill. Copying answers out of
the sources before the match is cheating. The line is simple: **did your input come from the game?**

---

## 1. Startup

```bash
# 1. Clear leftovers from the previous match (never while a match is running)
#    Preferred: python guard.py clean      (restores any sealed sources too)
#    Manual:    delete src/data/session.json, .running, .seal, .rules_ack
#               and remove the src/data/runtime leftovers except reports/

# 2. Non-interactive start (does not read stdin; safe for background use)
set TM_TRADER=MyAgent
set TM_EVENTS=1        # random events
set TM_FR=1            # Preferred Financing (unlimited loans, target range 0.01%~100%)
set TM_SLOT=0          # Slot Machine (3 plays, 80% nothing / 15% 5x / 5% 10x)
python run.py
```

> **Nothing is ever prompted.** Every setting comes from an environment variable; anything unset
> falls back to a default (`TM_TRADER=Guest`, `TM_EVENTS=1`, `TM_FR=1`, `TM_SLOT=1`, `TM_ASSIST=1`).
> Order at startup: server up → difficulty draw (30 s) → clock starts.
> Both global switches are read before the server starts.

### Writable area

`_agent/` in the project root is the writable workspace. Its **contents** are emptied on every
exit path — before a new match starts, on `/quit`, on timeout settlement, and on `/reset` — while
the directory itself stays. `.gitignore` ignores it, so nothing in it can reach the repository.

That cleanup covers `_agent/` only. Files written anywhere else (the project root, `src/`) are not
touched by it: `tools\deep-clean.ps1` clears `data/` (keeping `reports/`), `_agent/`, and stray `*.log`
files in the root, and reports any other untracked file it notices.

After startup:

- the HTTP server listens on `127.0.0.1:8734`
- the spectator GUI opens automatically (read-only)
- the difficulty draw counts down **30 seconds**

## 2. Lock the difficulty (mandatory — ticks do not advance before this)

The engine **does not advance the match** until difficulty is locked. Two ways:

```bash
# Option A: let the 30 seconds run out (random combination)
curl http://127.0.0.1:8734/roll/state
# → {"ok": true, "roll_left": 23.4, "rolled": false}

# Option B: lock it now (you get whatever combination is showing at that moment)
curl -X POST http://127.0.0.1:8734/roll/stop
```

Once locked, `rolled` becomes `true` and `difficulty` exposes `gap` / `liq` with their values.
The slot index is `gap + liq × 5` (0-24) and is printed on the report header; replaying with
`TM_ROLL_INDEX=<index>` pins the same slot. `TM_SEED` alone cannot reproduce the slot — it
follows the wall clock at roll_stop (one lap every 2.5 s).

**The match clock starts at the instant of locking** — the 30 seconds of drawing do not count
against the 45 minutes.

## 3. HTTP interface

Every endpoint lives at `http://127.0.0.1:8734`.

### Read-only

| Method | Path | Notes |
|---|---|---|
| GET | `/health` | Liveness; returns tick / equity / finished / protocol / engine_version |
| GET | `/state` | **Full board** (detailed below) |
| GET | `/rules` | Rule text |
| GET | `/prices` | Current prices and history per pair |
| GET | `/roll/state` | Difficulty countdown |
| GET | `/scratchpad` | Read scratchpad entries |

### Trading

| Method | Path | Body |
|---|---|---|
| POST | `/open` | `{"pair":"AURA/CORE","side":"LONG","lots":10,"leverage":100}` |
| POST | `/close` | `{"pair":"AURA/CORE","lots":10}`; if `lots` exceeds the held size it closes the whole position without error |
| POST | `/loan` | `{"amount":1000000}` |
| POST | `/repay` | `{"amount":600000}` |
| POST | `/close_all` | No argument: close every open position at the current price |

### Control

| Method | Path | Notes |
|---|---|---|
| POST | `/fastforward` | `{"seconds":300}`, tier must be 300 or 180 |
| POST | `/roll/start` | Start the draw |
| POST | `/roll/stop` | Lock the difficulty |
| POST | `/begin` | Release the pre-match freeze |
| POST | `/pause` | Freeze (**only valid before the match starts; afterwards always rejected**) |
| POST | `/trader` | `{"name":"MiniMax-M3.1"}`: set the operator name shown in the report title (max 60 chars, empty rejected) |
| POST | `/scratchpad` | `{"text":"..."}`, append an entry |
| GET | `/special` | Both global switches (`fr_left` is always `null` since v1.2.4) |
| POST | `/special` | `{"name":"fr"|"slot","on":true}`, toggle a switch (**start of match only**; rejected once the match has begun) |
| POST | `/slot` | `{"amount":10000}`, slot bet (1~200000, ≤ current equity, 3 plays) |
| POST | `/reset` | Start a new match |
| POST | `/quit` | Early exit: at or above the target the reason is `Target reached - early exit` (counts as reached); below it the reason is `Abandoned below target` (does not). **About 3 seconds later the service cleans up**: temp files removed, leftover port holders stopped |
| POST | `/shutdown` | Stop the server (**records one abnormal exit**) |

> `POST /quit` returns two settlement fields: `settled` (boolean, whether settlement was
> complete) and `warnings` (string array listing leftover positions or unpaid loans).
> When `settled=false` the report header reads "Settlement error"; do not treat it as a
> clean result.

## 4. The `/state` fields

> `GET /state?history=0` drops `price_history` (up to 2000 points per pair,
> growing through the match). With the parameter the response is smaller —
> trading endpoints (`/open` `/close` `/loan` …) already return the trimmed form,
> without history or the event feed.

```jsonc
{
  "tick": 120,
  "equity": 1043251.2,        // net value = cash + unrealised P&L − debt
  "balance": 1200000.0,       // cash
  "pnl_pct": 4.33,            // relative to starting capital

  "positions": [ {"pair":"AURA/CORE","side":"LONG","lots":10,"leverage":100,
                  "entry":150.2,"price":151.4,"upnl":12000,"margin":15140} ],
  "margin_level": 680.5,      // equity / (notional x 10%); < 100% margin call, < 50% forced liquidation,
                              // open orders must leave >= 150%

  "prices": {"AURA/CORE": {"price":151.4, "spread_pct":0.06}},

  "loan": {"balance":0, "limit":3000000, "borrowed":0, "interest":0},
  "total_borrowed": 0,

  "active_mods": [                      // active events (object list, at most 6 entries)
    {"key": "loan_pool_mult", "name": "Central bank easing", "value": 1.35,
     "label": "loan pool x1.35", "left_ticks": 42}
  ],
  "loan_bump_range": [1.0, 100.0],      // borrow uplift range (%): [1,100] normally, [0.01,100] with Preferred Financing
  "special": {                          // the two global switches
    "fr": true, "fr_left": null,        // Preferred Financing on; the per-run cap is gone, so this is always null
    "slot": false, "slot_left": 3,      // Slot Machine off
    "slot_win": 0.0, "fr_lo_pct": 0.01  // total slot winnings / borrow lower bound (%), 0.01 when on, 1.0 when off
  },
  "seed": null,                         // always null during a match; the seed is returned after settlement, for replay

  "gap_level": "low", "liq_level": "normal",
  "ff": {                               // fast-forward budget (an object, not a flat field)
    "total": 900, "used": 0, "remain": 900,
    "records": [], "cool_left": 0, "last_cd": 0,
    "can5": true, "can3": true, "left5": 3, "left3": 5
  },
  "finished": false,
  "settlement": null,                   // settlement result: {settled, warnings, reason}; null before the run ends
  "audit": [],                          // ledger audit: empty array means cash/positions/loan/equity all reconcile
  "events": [ ... ]                     // recent events, full text included
}
```

### Seven things to check

1. **`equity` vs `target`** — how far you still have to go
2. **`margin_level`** — equity / (notional exposure x 10%); below 100% you need more margin, below 50% you get liquidated, opening orders must keep >= 150%
3. **`active_mods`** — which temporary rules are currently moving prices
4. **`loan_bump_range`** — the current cost of borrowing (`[1,100]` normal, `[0.01,100]` Preferred Financing)
5. **`special`** — whether the switches are on; `slot_left` is the remaining slot plays, while `fr_left` is always `null` since v1.2.4 removed the loan-count cap (field kept for compatibility)
6. **`ff`** — the fast-forward budget object: `remain` is seconds left, `cool_left` is the remaining cooldown,
   and `can5` / `can3` tell you straight away whether each step is usable right now
7. **`events`** — what just happened (**full text, no need to consult the docs**)

## 5. Fast-forward budget rules

900 seconds (15 minutes) per match, two tiers:

| Tier | Advance | Cooldown |
|---|---|---|
| 5 minutes | 300 s | 120 s |
| 3 minutes | 180 s | 90 s |

**The cooldown follows the tier you used.** If remaining budget cannot cover the tier, the jump
does not execute.

```bash
curl -X POST http://127.0.0.1:8734/fastforward \
     -H "Content-Type: application/json" -d '{"seconds":300}'
# → {"ok":true,"ticks":60,"state":{...}}
# during cooldown → {"ok":false,"error":"Fast-forward cooling down, 78 s left (manual advance is also blocked during cooldown)"}
```

## 6. Scratchpad (optional)

Scratchpad entries are merged into the HTML report at settlement so a human can see
*why* a decision was made.

```bash
curl -X POST http://127.0.0.1:8734/scratchpad \
     -H "Content-Type: application/json" \
     -d '{"text":"t120 AURA is 8% off the mean, going short"}'
```

Git Bash's `curl -d` encodes Chinese text as GBK; the server decodes it as UTF-8 and
receives mojibake.

## 6.5. Ending early

`POST /quit` is a **normal settlement**, not an abnormal exit, but the end reason splits in two:

- **equity >= target -> `Target reached - early exit`**: counts as reached. Stopping once you have
  made enough is skill in the real world, and this is a valid early exit.
- **equity < target -> `Abandoned below target`**: does not count.

Both close all positions immediately, clear loans and generate the full report; final equity is
taken at that instant and rating/cost attribution are produced as usual. There is **no penalty,
no abnormal flag, no effect on starting the next match**. They are distinguished because
"locked in a gain" and "gave up" would otherwise look identical in the statistics.

Hitting the target and choosing to keep holding is also allowed: the first moment it is hit is
recorded in `/state` as `hit_at_tick`. If equity later slides back below the target, the final
verdict is still "target missed", and the report says it hit the target at m:ss and gave it back.
While holding past the target the engine runs at 4x pace (`TM_TAIL_SPEED=1` restores the real
pace); prices are tick-driven, so nothing about the outcome changes.

There are exactly two abnormal exits: `POST /shutdown` (stop immediately, leaves an "unsettled"
marker) and killing the process.

## 7. Finishing

```bash
curl -X POST http://127.0.0.1:8734/quit
# → {"ok":true,"final_equity":...,"report":"...html"}
```

The report lands under `data/reports/`.

**`/shutdown` is not a normal end** — it records an abnormal exit and the report shows "unsettled".
Use `/quit` when you have actually finished.

## 8. Safety boundaries

These validations cannot be bypassed:

- amounts must be finite positive numbers (`NaN` / `Infinity` / negatives / strings are all rejected)
- borrowing beyond the available limit is rejected
- out-of-range lots or leverage are rejected
- **after settlement every write is rejected** (`finished=true` makes open/close/loan/repay all
  return "This run is already over")
- concurrent requests are protected by a `LOCK`; simultaneous orders result in exactly one success

**The one thing that cannot be protected against is your own faulty logic** — the engine is
deterministic: the same input always produces the same output.

### Outside Mercy (optional, on by default)

```bash
POST /assist/ask      {"text": "..."}                     # 3 asks per match; returns a ticket
GET  /assist/inbox                                        # collect spectator messages (once each)
POST /assist/enable                                       # enable mid-match for 500,000 cash
GET  /assist/pending                                      # the spectator GUI polls this
POST /assist/reply    {"ticket": "a1", "text": "..."}     # spectators answer
POST /assist/reject   {"ticket": "a1"}                    # spectators decline
```

Set `TM_ASSIST=1` before starting to enable it for free. Asking does not block: `/assist/ask`
returns at once and the contestant polls `/assist/inbox` on its own schedule.

**Replies never enter the `/state` event feed.** Polling only `/state` means never seeing
the answer -- `/state` carries just `assist_unread` (the unread count); the text itself needs
`GET /assist/inbox`. Fetching marks them read; unread ones stay queued.
