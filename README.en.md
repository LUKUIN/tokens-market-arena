# Tokens Trading Market · AI Edition (source)

[![CI](https://github.com/LUKUIN/tokens-market-arena/actions/workflows/ci.yml/badge.svg?branch=main)](https://github.com/LUKUIN/tokens-market-arena/actions/workflows/ci.yml)

> [中文](README.md) · **English**

> Corresponds to packaged build **v97**. The model trades through an HTTP API; the GUI is only a
> **read-only spectator**. **Not interchangeable with the Human edition**
> (`TokensMarket-OpenSource-Human`): this edition has no investment panel, no buy/sell buttons,
> no fast-forward buttons. Do not copy UI files between the two.

---

## What this is

A 45-minute trading simulator: 1,000,000 in starting capital, the goal is to double it.
The participant is a large language model, not a human.

- The model opens positions, closes them, borrows, and advances time over HTTP;
- A human watches the account, positions, equity curve and event feed in a spectator window;
- Whatever the model writes in the **scratchpad** is visible via the **"AI 行为"** button in the
  spectator's top-right corner (read-only);
- Every match generates a self-contained HTML report, with the scratchpad merged in.

---

## Quick start

For agents and scripts (recommended, non-interactive):

```bat
set TM_TRADER=DeepSeek-V4-Flash-high-DeepSeekHarness
set TM_EVENTS=1
set TM_FR=1
set TM_SLOT=0
python run.py
```

Double-click launcher:

```
开一局.bat        (zero prompts, same as `python run.py`, spectator included)
or  python run.py --interactive   (human demo only; asks model ID and event mode)
```

Service without a window (no-desktop environments only; the spectator is otherwise mandatory):

```
python run.py --headless          # same as: python run.py server --headless
```

### Environment variables

| Variable | Purpose |
|---|---|
| `TM_TRADER` | Contestant ID, format **`<model>-<effort>-<agent-platform>`**, max 60 chars, defaults to `访客` |
| `TM_EVENTS` | `1` enable random events / `0` ideal conditions (black-swan gaps only) |
| `TM_FR` | `1` enables **Preferred Financing**: no cap on the number of loans (bounded by the 300,000 pool), target range `0.01%~100%` (always raises) |
| `TM_SLOT` | `1` enables **Slot Machine**: **3** plays, `1~200000` and ≤ current equity, 80% nothing / 15% 5× / 5% 10× |
| `TM_PORT` | Service port, default `8734`. Change this instead of editing code |
| `TM_SIGN_KEY` | HMAC key for save files; a dev placeholder is used when unset |

Requirements: **Python 3.14.7** (pinned at `C:/Users/User/AppData/Local/Programs/Python/Python314/python.exe`), Windows (the spectator uses Win32 window-icon APIs), no third-party dependencies. `run.py` rejects any other Python version with exit code 2; do not substitute 3.10-3.13.

---

## How a match runs

0. **Startup Q&A (fixed order)**: player name → random events on/off → **Preferred Financing** on/off →
   **Slot Machine** on/off. Supply all four via env vars and nothing is asked;
   `run.py` prompts only for whatever is missing, and `input()` treats EOF as **off**.
   **Both global switches are decided after the events question and before the difficulty draw.**
1. The server starts and the spectator window appears, titled "drawing difficulty".
2. 30-second difficulty draw: the model may call `POST /roll/stop` to lock it early, otherwise it
   locks automatically when the countdown ends.
3. The clock starts the moment difficulty is locked — the 30 seconds of drawing do not count
   against the 45 minutes.
4. Trading begins: `/state` to read the board → `/open` `/close` to trade → `/fastforward` to advance time.
5. At 45 minutes, on hitting the target, on liquidation, or on `/quit`, the match settles and the
   report is written.
6. About 3 seconds after `/quit` the server and spectator exit on their own.

---

## HTTP API

Base URL defaults to `http://127.0.0.1:8734`.

### GET

| Endpoint | Returns |
|---|---|
| `/health` | `{ok, tick, equity, finished, protocol, engine_version}`. `protocol` is the API
  contract version; `engine_version` is the release |
| `/rules` | Full rule text, parameters and a 20-endpoint list (random events are only announced at runtime through `events` in `/state`) |
| `/state` | Account, positions, loan, quotes, history, difficulty, fast-forward state |
| `/prices` | Quote table |
| `/roll/state` | Difficulty countdown and the currently locked result |
| `/scratchpad` | All scratchpad entries for this match |
| `/special` | Both global switches (`fr`/`slot`/`slot_left`/`slot_win`; `fr_left` is always `null` since v1.2.4) |

### POST (JSON body)

| Endpoint | Body | Notes |
|---|---|---|
| `/open` | `{pair, side, lots, leverage}` | Open a position |
| `/close` | `{pair, lots}` | Close; lots above the held size closes the whole position |
| `/close_all` | — | Close everything |
| `/fastforward` | `{seconds}` | Jump one tier (300 or 180), consumes budget |
| `/loan` | `{amount}` | Borrow; the target-uplift percentage is drawn at borrow time — that is the cost |
| `/repay` | `{amount}` | Repay; omit the amount to repay in full |
| `/trader` | `{name}` | Set the player name |
| `/scratchpad` | `{text}` | Append a scratchpad entry |
| `/special` | `{name, on}` | Toggle a global switch (`fr` / `slot`); **start of match only**, rejected once the match has begun |
| `/slot` | `{amount}` | Slot bet: `1~200000`, ≤ current equity, 3 plays per match |
| `/pause` / `/begin` | — | Freeze / resume the clock |
| `/roll/start` / `/roll/stop` | — | Start / lock the difficulty draw |
| `/reset` | — | Start over (clears `data/` except `reports/`) |
| `/quit` | — | Settle normally and exit |
| `/shutdown` | — | Stop immediately (leaves an abnormal-exit report) |

> **Note**: `/fastforward` is the only way to advance time: 300 or 180 seconds per step.
> Budget is 900 seconds,
> tiers are 300/180 seconds, cooldowns are 120/90 seconds. Calls during cooldown are rejected;
> the server also advances on its own every 5 seconds.

> **Token saving**: add `?history=0` to `/state` to drop `price_history` (up to 2000 points per
> pair). Order-placing endpoints already return a trimmed state — no history, no event feed.

---

## Scratchpad CLI (optional)

Lets the model record its reasoning during the match. It takes no space in the spectator's main
layout — the human clicks **"AI 行为"** in the top-right corner to open a read-only window, and the
contents are merged into the HTML report afterwards.

```bash
# record one entry
curl -X POST http://127.0.0.1:8734/scratchpad      -H "Content-Type: application/json" -d '{"text":"AURA is 8% off the mean, short"}'
# list entries for this match
curl -s http://127.0.0.1:8734/scratchpad
# count only
curl -s "http://127.0.0.1:8734/scratchpad?count=1"
# clear
curl -s -X POST http://127.0.0.1:8734/scratchpad      -H "Content-Type: application/json" -d '{"clear":true}'
```

Over HTTP: `GET /scratchpad`, `POST /scratchpad {"text": "..."}`.

Every entry is flushed to disk (`src/data/.scratchpad.jsonl`) immediately, so closing the terminal
mid-match loses nothing. Cleared on settle/reset. You may skip it entirely — the report will say
"no entries".

---

## Deep process cleanup

Run this after a match, or when startup misbehaves (port taken, window never appears):

```bash
cd "D:/DeepSeek Harness WorkSpace/TokensMarket-OpenSource-AI-v97"
powershell -NoProfile -ExecutionPolicy Bypass -File deep-clean.ps1
```

> **When calling from an AI agent or a script, use the command above.** Do not run
> `进程深度清理.bat` directly: it contains two `pause` calls (stdin piped in will hang) and prints
> GBK text (garbled in a UTF-8 terminal). `deep-clean.ps1` is the same logic in non-interactive
> form and forces UTF-8 output; **exit code 0 means success**.
> Double-clicking the `.bat` still works for humans (pass `-y` to skip the pauses).

It does two things:

1. Kills leftover Python game processes by command-line keyword and by ports 8734–8745;
2. Removes every runtime file under `src/data/` except `reports/` (including the scratchpad cache).

`reports/` holds historical match reports and is never touched.

---

## Repository layout

```
TokensMarket-OpenSource-AI-v97/
├── run.py                  entry point (ai / --interactive / server / state)
├── 开一局.bat            Windows double-click launcher
├── 进程深度清理.bat        manual double-click cleanup (contains pause)
├── deep-clean.ps1          cleanup implementation; agents should call this directly
├── src/
│   ├── tm_engine.py        engine (pure logic)
│   ├── tm_api.py           HTTP layer
│   ├── tm_watch_ai.py      read-only spectator
│   ├── scratchpad.py       scratchpad CLI
│   ├── app.ico / warn.ico  icons
├── docs/
│   ├── rules.md            full rules (Chinese)      · rules.en.md (English)
│   ├── cost-model.md       cost model (Chinese)      · cost-model.en.md (English)
│   └── ai-protocol.md      agent protocol (Chinese)  · ai-protocol.en.md (English)
├── examples/reports/       6 representative reports
└── src/data/               generated at runtime: session.json, reports/, .scratchpad.jsonl
```

---

## Differences from the Human edition (do not mix)

| | AI edition (this repo) | Human edition |
|---|---|---|
| UI | Read-only spectator | Full interactive GUI |
| Investment panel | None | Yes |
| Opening positions | HTTP `/open` | Buttons |
| Fast-forward | `/fastforward` | Two step buttons (5 min / 3 min) |
| Scratchpad | Yes | No |
| Resolution | Fixed 1920×1080 layout | Four options with scaling |
| Process cleanup script | Yes | No |

---

## Measured results

Six large models, one match each, same rules (45 minutes / 1,000,000 capital / double the target):

| Model | Final equity | P&L | Outcome |
|---|---:|---:|---|
| qwen3.8-flash | **2,063,829** | **+106.38%** | Hit the target (only one) |
| GLM-5.3-Flash | 909,030 | −9.10% | Missed |
| Doubao-Seed | 676,243 | −32.38% | Missed |
| WorkBuddy-Agent | 230,483 | −76.95% | Missed |
| DeepSeek-Flash | 163,587 | −83.64% | Missed |
| (one model, single match) | −1,298,657 | −229.87% | Blown out |

> **Sample size is tiny.** Variance between matches is extreme, and doubling the target is close to
> a fair coin. Treat this as a demonstration of the mechanics, **not** a model ranking.

---

## Settlement and liquidation

When a match ends (`POST /quit`, time up, blow-up, negative cash), the engine wraps up in three fixed steps:

1. **Force-close everything** - not blocked by "exchange maintenance" or any other halt.
   Fills use the unified cost path (mid price minus/plus half spread plus slippage), identical to
   a manual close, and are written to the trade log.
2. **Clear the loan** - debt is deducted from cash and `loan.balance` goes to zero.
3. **Verify invariants** - no positions left, no outstanding debt.

Final equity = cash - debt, with **no floating P&L**.

`POST /quit` returns two extra fields:

| Field | Meaning |
|---|---|
| `settled` | Boolean. `false` means settlement found a problem (leftover positions, unpaid loan) |
| `warnings` | String array with the specific problem, e.g. "1 position(s) could not be settled" |

Whenever `warnings` is non-empty the report header reads
"Settlement error (N position(s) left open)" instead of a normal verdict. The report also gains two
rows under the key metrics: "Left open after settlement" and "Forced liquidation".

**Blow-up liquidation** (margin level below the stop-out line, or a margin call timing out) uses
the same cost path - spread, slippage and fees all apply - and its fills carry a `forced` flag.
The report lists a separate "Forced liquidation" count.

> **Fixed in v1.0.12**: settlement closes used to be silently skipped during "exchange
> maintenance", the blow-up path charged fees only (no spread or slippage), and the reported random
> seed could not reproduce a run unless `TM_SEED` was set explicitly. All three are fixed;
> historical reports use a different cost basis and are not directly comparable.

## Ledger audit and paired benchmark

### Ledger audit (`audit`)

Before settlement and on every `/state`, four identities are checked:

| Check | Identity |
|---|---|
| Fees | accumulated fees == sum of `fee` over the trade log |
| Loan | `loan.balance` == `borrowed - repaid + interest` |
| Positions | side is `LONG` / `SHORT`, lots strictly positive |
| Equity | `equity` == cash + unrealized P&L - debt |

`audit` is a string array: **empty means all four hold**. Any entry is a human-readable warning.
At settlement the audit verdict is merged into `warnings`, so `settled` becomes `false` — a mismatch
is never reported as a clean settlement.

The same verdict has three exits, so nobody has to dig through JSON:

- the `audit` field of `/state` (for agents and scripts)
- the spectator status bar (red text on failure, empty when clean)
- one line under the report's key metrics (green = passed, red = failed with the exact identity)

### Event sequence

Every event carries `seq` (monotonic) and `session` (session id), so reports and audit logs can be
cross-referenced by number.

### Machine-readable summary

Each HTML report is accompanied by a same-named JSON file (`reports/<stamp>_<trader>.json`) holding
version, seed, P&L, drawdown, Sharpe, cost breakdown, settlement result and audit verdict.
`bench.py` and CI read that JSON instead of parsing HTML.

### Paired benchmark (`bench.py`)

Single-match variance is enormous (+106% to -229% in the historical samples), so one match says
nothing. Evaluation runs the same seed set for the same number of rounds:

```bash
python bench.py run --seeds 1,2,3 --policy probe      # three matches
python bench.py run --seeds 1-5 --policy noop         # five no-op baseline matches
python bench.py summary --dir src/data/reports        # summarise existing summaries
```

`run` advances ticks in-process (no HTTP, no wall-clock wait) and writes one JSON summary per match.
`summary` prints mean, median, stdev, P10/P90, worst drawdown, target hits, settlement errors and
audit-pass counts. The built-in policies (`noop`, `probe`) are headless baselines, not model results.

## Known limits

- **Windows only** (the spectator's window icon and notification sound go through Win32 APIs).
- Engine and spectator share one process; if the spectator crashes, the match ends.
- This source edition has no `.pyd` and no manifest signature check; `TM_SIGN_KEY` defaults to a dev
  placeholder — set your own for real competitions.
- A full 45-minute stress run has not been performed; only short matches were verified.
- Documentation ships in both languages (`*.md` Chinese, `*.en.md` English). Runtime messages
  (errors, event names, the HTML report) are still Chinese in this source edition.
