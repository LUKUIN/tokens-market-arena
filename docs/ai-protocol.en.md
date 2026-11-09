# Agent Integration Protocol

> [中文](ai-protocol.md) · **English**

The HTTP interface is designed for **one thing: letting a large model understand the board in as
few tokens as possible and make a decision**.

> **Play this match yourself. You do not need to ask the game operator anything.**
> Only report actual bugs: the API contradicting this document, self-contradictory numbers, a
> crash, or visibly corrupted data.
> Difficulty choice, whether to borrow, when to cut a loss, whether to play the slot machine —
> decide all of it yourself. That is the game.

> **Note on language**: in this source edition, runtime messages returned by the API
> (errors, event text, report) are in Chinese. Examples below keep the original Chinese strings
> so you can match what you actually receive.

## 1. Startup

> **Runtime requirement**: Python **3.14.7** (the pinned path on this machine is `C:\Users\User\AppData\Local\Programs\Python\Python314\python.exe`;
> on another machine any 3.14 install works, whatever the location).
> `run.py` validates the version before doing anything else and exits with code 2 on a mismatch.
> Every `python` in the commands below means your own 3.14 path.
> The spectator window opens automatically: `run.py`, `run.py server` and `开一局.bat` behave
> identically since v1.0.11. `--headless` is the only windowless mode (no-desktop environments only).

```bash
# 1. Clear leftovers from the previous match (do not do this while a match is running)
#    Delete data/session.json, .running, .seal, .watch.pid, .rules_ack

# 2. Non-interactive start (does not read stdin; safe for background use)
set TM_TRADER=MyAgent
set TM_EVENTS=1        # random events
set TM_FR=1            # Preferred Financing (unlimited loans, target range 0.01%~100%)
set TM_SLOT=0          # Slot Machine (3 plays, 80% nothing / 15% 5x / 5% 10x)
python run.py
```

> **The prompt order is fixed**: player name → random events → Slot Machine / Preferred Financing →
> server starts → 30-second difficulty draw.
> Both global switches are decided after the events question and before the difficulty draw.
> Only when all four variables are supplied does it ask nothing; `run.py` prompts for whichever is
> missing (`input()` reading EOF takes the default "off").

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
| GET | `/special` | Both global switches (`fr_left` is always `null` since v1.2.4) |
| POST | `/special` | `{"name":"fr"|"slot","on":true}`, toggle a switch (**start of match only**; rejected once the match has begun) |
| POST | `/slot` | `{"amount":10000}`, slot bet (1~200000, ≤ current equity, 3 plays) |
| POST | `/reset` | Start a new match |
| POST | `/quit` | Settle voluntarily and generate the report |
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
  "margin_level": 680.5,      // < 100% margin call, < 50% forced liquidation

  "prices": {"AURA/CORE": {"price":151.4, "spread_pct":0.06}},

  "loan": {"balance":0, "limit":3000000, "borrowed":0, "interest":0},
  "total_borrowed": 0,

  "active_mods": [                      // active events (object list, at most 6 entries)
    {"key": "loan_pool_mult", "name": "央行放水", "value": 1.35,
     "label": "贷款池 ×1.35", "left_ticks": 42}
  ],
  "loan_bump_range": [1.0, 100.0],      // borrow uplift range (%): [1,100] normally, [0.01,100] with Preferred Financing
  "special": {                          // the two global switches
    "fr": true, "fr_left": null,        // Preferred Financing on; the per-run cap is gone, so this is always null
    "slot": false, "slot_left": 3,      // Slot Machine off
    "slot_win": 0.0, "fr_lo_pct": 0.01  // total slot winnings / borrow lower bound (%), 0.01 when on, 1.0 when off
  },
  "seed": 20261105,                     // random seed for this match (written into the report)

  "gap_level": "低", "liq_level": "正常",
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
# during cooldown → {"ok":false,"error":"快进冷却中，还需 78 秒"}
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

`POST /quit` is a **normal settlement**, not an abnormal exit:

- all positions are closed immediately, loans cleared, the full report generated
- final equity is taken at that instant; rating, cost attribution and trade list are all produced
- **no penalty, no abnormal flag, no effect on starting the next match**
- the only difference from "45 minutes elapsed" is the end reason recorded in the report

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
  return "本局已结束")
- concurrent requests are protected by a `LOCK`; simultaneous orders result in exactly one success

**The one thing that cannot be protected against is your own faulty logic** — the engine is
deterministic: the same input always produces the same output.
