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

Manual demo (double-click):

```
双击  开一局.bat        (asks for model ID and event mode)
or    python run.py --interactive
```

Server only, no spectator window (headless, bring your own UI):

```
python run.py server 127.0.0.1 8734
```

### Environment variables

| Variable | Purpose |
|---|---|
| `TM_TRADER` | Contestant ID, format **`<model>-<effort>-<agent-platform>`**, max 60 chars, defaults to `访客` |
| `TM_EVENTS` | `1` enable random events / `0` ideal conditions (black-swan gaps only) |
| `TM_FR` | `1` enables **Finance Reversal**: at most **2** loans per match, target range `-20%~100%` |
| `TM_SLOT` | `1` enables **Slot Machine**: **3** plays, `1~200000` and ≤ current equity, 80% nothing / 15% 5× / 5% 10× |
| `TM_PORT` | Service port, default `8734`. Change this instead of editing code |
| `TM_SIGN_KEY` | HMAC key for save files; a dev placeholder is used when unset |

Requirements: Python 3.10+, Windows (the spectator uses Win32 window-icon APIs), no third-party dependencies.

---

## How a match runs

0. **Startup Q&A (fixed order)**: player name → random events on/off → **Finance Reversal** on/off →
   **Slot Machine** on/off. Supply all four via env vars and nothing is asked;
   `run.py` prompts only for whatever is missing, and `input()` treats EOF as **off**.
   **Both global switches are decided after the events question and before the difficulty draw.**
1. The server starts and the spectator window appears, titled "drawing difficulty".
2. 30-second difficulty draw: the model may call `POST /roll/stop` to lock it early, otherwise it
   locks automatically when the countdown ends.
3. The clock starts the moment difficulty is locked — the 30 seconds of drawing do not count
   against the 45 minutes.
4. Trading begins: `/state` to read the board → `/open` `/close` to trade → `/tick` to advance.
5. At 45 minutes, on hitting the target, on liquidation, or on `/quit`, the match settles and the
   report is written.
6. About 3 seconds after `/quit` the server and spectator exit on their own.

---

## HTTP API

Base URL defaults to `http://127.0.0.1:8734`.

### GET

| Endpoint | Returns |
|---|---|
| `/health` | `{ok, tick, equity, finished}` |
| `/rules` | Full rule text plus parameters (including all 38 random events) |
| `/state` | Account, positions, loan, quotes, history, difficulty, fast-forward state |
| `/prices` | Quote table |
| `/roll/state` | Difficulty countdown and the currently locked result |
| `/scratchpad` | All scratchpad entries for this match |
| `/special` | Both global switches plus remaining uses (`fr`/`slot`/`fr_left`/`slot_left`/`slot_win`) |

### POST (JSON body)

| Endpoint | Body | Notes |
|---|---|---|
| `/open` | `{pair, side, lots, leverage}` | Open a position |
| `/close` | `{pair, lots}` | Close; lots above the held size closes the whole position |
| `/close_all` | — | Close everything |
| `/tick` | — | Advance one tick (**consumes fast-forward budget, subject to cooldown**) |
| `/fastforward` | `{seconds}` | Jump one tier (300 or 180), consumes budget |
| `/loan` | `{amount}` | Borrow; the target-uplift percentage is drawn at borrow time — that is the cost |
| `/repay` | `{amount}` | Repay; omit the amount to repay in full |
| `/trader` | `{name}` | Set the player name |
| `/scratchpad` | `{text}` | Append a scratchpad entry |
| `/special` | `{name, on}` | Toggle a global switch (`fr` / `slot`); enabling mid-match costs 300,000 cash |
| `/slot` | `{amount}` | Slot bet: `1~200000`, ≤ current equity, 3 plays per match |
| `/pause` / `/begin` | — | Freeze / resume the clock |
| `/roll/start` / `/roll/stop` | — | Start / lock the difficulty draw |
| `/reset` | — | Start over (clears `data/` except `reports/`) |
| `/quit` | — | Settle normally and exit |
| `/shutdown` | — | Stop immediately (leaves an abnormal-exit report) |

> **Note**: `/tick` and `/fastforward` share one budget and one cooldown. Budget is 900 seconds,
> tiers are 300/180 seconds, cooldowns are 120/90 seconds. Calls during cooldown are rejected;
> the server also advances on its own every 5 seconds.

> **Token saving**: add `?history=0` to `/state` to drop `price_history` (up to 2000 points per
> pair). Order-placing endpoints already return a trimmed state — no history, no event feed.

---

## Scratchpad CLI (optional)

Lets the model record its reasoning during the match. It takes no space in the spectator's main
layout — the human clicks **"AI 行为"** in the top-right corner to open a read-only window, and the
contents are merged into the HTML report afterwards.

```bat
python src/scratchpad.py "AURA is 8% off the mean, preparing to short"
python src/scratchpad.py --list     list entries for this match
python src/scratchpad.py --count    count only
python src/scratchpad.py --clear    clear
python src/scratchpad.py            continuous input mode (Ctrl+C to exit)
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
├── examples/reports/       4 representative reports
└── src/data/               generated at runtime: session.json, reports/, .scratchpad.jsonl
```

---

## Differences from the Human edition (do not mix)

| | AI edition (this repo) | Human edition |
|---|---|---|
| UI | Read-only spectator | Full interactive GUI |
| Investment panel | None | Yes |
| Opening positions | HTTP `/open` | Buttons |
| Fast-forward | `/fastforward` + `/tick` | Two buttons |
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

## Known limits

- **Windows only** (the spectator's window icon and notification sound go through Win32 APIs).
- Engine and spectator share one process; if the spectator crashes, the match ends.
- This source edition has no `.pyd` and no manifest signature check; `TM_SIGN_KEY` defaults to a dev
  placeholder — set your own for real competitions.
- A full 45-minute stress run has not been performed; only short matches were verified.
- Documentation ships in both languages (`*.md` Chinese, `*.en.md` English). Runtime messages
  (errors, event names, the HTML report) are still Chinese in this source edition.
