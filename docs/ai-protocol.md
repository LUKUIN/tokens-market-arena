# Agent Integration Protocol

The HTTP interface is designed for **one thing: letting a large model understand the board in as
few tokens as possible and make a decision**.

> **What counts as a bug report**: the API contradicting this document, self-contradictory
> numbers, a crash, or visibly corrupted data. Everything else — the difficulty draw, borrowing,
> cutting a loss, the slot machine — is decided inside the game by whoever is playing.

> **Note on language**: in this source edition, runtime messages returned by the API
> (errors, event text, report) are in Chinese. Examples below keep the original Chinese strings
> so you can match what you actually receive.

## 0. Before you start: required reading, hard rules

### Requirements

1. **Read every `.md` file in this repository first** — `README.md` plus everything under `docs/` —
   and understand the rules, the interface and the cost model before making a move.
   Do not read them mid-match; that turns the rules into a crutch.
2. **Use the pinned runtime, and start with the spectator window open.**
   - Python **3.14.7 only**: `C:/Users/User/AppData/Local/Programs/Python/Python314/python.exe`.
     `run.py` checks this first; a wrong version exits with code 2 and prints the correct command.
     Do not call `where python` or `py -3.x` to hunt for another interpreter — the GUI widgets and
     the `.pyc` files are built for 3.14. Every `python` in the commands below means that path.
   - The start command is `run.py`, and a human has to be able to watch your equity, positions and
     event feed live. Since v1.0.11 `run.py`, `run.py server` and `Start Match.bat` behave
     identically and all open the read-only spectator; "use server to skip the window" no longer exists.
   - `--headless` is the only windowless mode, allowed only where there is genuinely no desktop
     (CI, containers, pure SSH). It is forbidden for a local match.
   - If you closed the window by accident, attach again with `Spectator.bat` (or
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
set TM_FR=1            # Preferred Financing (max 2 loans, target range 0%~100%)
set TM_SLOT=0          # Slot Machine (3 plays, 80% nothing / 15% 5x / 5% 10x)
python run.py
```

> **Nothing is ever prompted.** Every setting comes from an environment variable; anything unset
> falls back to a default (`TM_TRADER=Guest`, `TM_EVENTS=0`, `TM_FR=0`, `TM_SLOT=0`).
> Order at startup: server up → difficulty draw (30 s) → clock starts.
> Both global switches are read before the server starts.

### Writable area

`_agent/` in the project root is the writable workspace. Its **contents** are emptied on every
exit path — before a new match starts, on `/quit`, on timeout settlement, and on `/reset` — while
the directory itself stays. `.gitignore` ignores it, so nothing in it can reach the repository.

That cleanup covers `_agent/` only. Files written anywhere else (the project root, `src/`) are not
touched by it: `deep-clean.ps1` clears `data/` (keeping `reports/`), `_agent/`, and stray `*.log`
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
| GET | `/special` | Both global switches plus remaining uses |
| POST | `/special` | `{"name":"fr"|"slot","on":true}`, toggle a switch (enabling mid-match costs 300,000 cash) |
| POST | `/slot` | `{"amount":10000}`, slot bet (1~200000, ≤ current equity, 3 plays) |
| POST | `/reset` | Start a new match |
| POST | `/quit` | Settle voluntarily and generate the report; **about 3 seconds later the service cleans up**: temp files removed, leftover port holders stopped |
| POST | `/shutdown` | Stop the server (**records one abnormal exit**) |

> `POST /quit` returns two settlement fields: `settled` (boolean, whether settlement was
> complete) and `warnings` (string array listing leftover positions or unpaid loans).
> When `settled=false` the report header reads "Settlement error"; do not treat it as a
> clean result.

## 4. The `/state` fields that matter

> **Token saving**: `GET /state?history=0` drops `price_history` (up to 2000 points per pair,
> growing through the match). If you only need to judge the board, always pass this —
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
  "margin_level": 680.5,      // < 100% margin call, < 50% forced liquidation

  "prices": {"AURA/CORE": {"price":151.4, "spread_pct":0.06}},

  "loan": {"balance":0, "limit":3000000, "borrowed":0, "interest":0},
  "total_borrowed": 0,

  "active_mods": ["Central bank easing"],  // names of currently active events
  "loan_bump_range": [1.0, 100.0],      // borrow uplift range (%): [1,100] normally, [-20,100] with Preferred Financing
  "special": {                          // the two global switches
    "fr": true, "fr_left": 2,           // Preferred Financing on, 2 loans left
    "slot": false, "slot_left": 3,      // Slot Machine off
    "slot_win": 0.0, "fr_lo_pct": -20.0 // total slot winnings / borrow lower bound (%)
  },
  "seed": 20261105,                     // random seed for this match (written into the report)

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
2. **`margin_level`** — below 100% you need more margin, below 50% you get liquidated
3. **`active_mods`** — which temporary rules are currently moving prices
4. **`loan_bump_range`** — the current cost of borrowing (`[1,100]` normal, `[-20,100]` Preferred Financing)
5. **`special`** — whether the switches are on and how many uses remain (`fr_left` / `slot_left`)
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

Record your reasoning. It is merged into the HTML report at settlement so a human can see
*why* you did what you did.

```bash
curl -X POST http://127.0.0.1:8734/scratchpad \
     -H "Content-Type: application/json" \
     -d '{"text":"t120 AURA is 8% off the mean, going short"}'
```

Or without the service:

```bash
python src/scratchpad.py --list
```

**Note**: Git Bash's `curl -d` converts Chinese text to GBK, which the server cannot decode.
Either send requests from Python, or write the entries in English.

## 6.5. Is ending early a problem?

`POST /quit` is a **normal settlement**, not an abnormal exit:

- all positions are closed immediately, loans cleared, the full report generated
- final equity is taken at that instant; rating, cost attribution and trade list are all produced
- **no penalty, no abnormal flag, no effect on starting the next match**
- the only difference from "45 minutes elapsed" is the end reason recorded in the report

There are exactly two abnormal exits: `POST /shutdown` (stop immediately, leaves an "unsettled"
marker) and killing the process.

So if you are satisfied with the result, ending early is safe; the only cost is the potential gain
you give up in the remaining time.

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

### Outside Mercy (optional, off by default)

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
