# Tokens Trading Market · AI Edition (source)

[![CI](https://github.com/LUKUIN/tokens-market-arena-en/actions/workflows/ci.yml/badge.svg?branch=main)](https://github.com/LUKUIN/tokens-market-arena-en/actions/workflows/ci.yml)

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
- Whatever the model writes in the **scratchpad** is visible via the **"AI Notes"** button in the
  spectator's top-right corner (read-only);
- Every match generates a self-contained HTML report, with the scratchpad merged in.

---

## Quick start

**This edition never prompts for input.** Every setting comes from environment variables; anything
unset falls back to a default. There is no `input()`, no "press any key", no confirmation step.

### For an agent or script (the normal case)

`python run.py` runs **in the foreground for the whole match** — up to 45 minutes. A harness that
executes it as a blocking command reaches its own timeout, kills the process, and the server
disappears; every later request then fails with `connection refused`.

`python run.py` opens the spectator window as well; `run.py server` is the headless mode and opens
no window.

Background start followed by a readiness poll:

```bash
cd <project-directory>

TM_TRADER="Doubao-1.5-pro-thinking-coze" TM_EVENTS=1 TM_FR=0 TM_SLOT=0 \
  nohup python run.py > run.log 2>&1 &

for i in $(seq 1 30); do
  curl -sf http://127.0.0.1:8734/health >/dev/null 2>&1 && break
  sleep 1
done
```

On Windows `cmd`:

```bat
cd /d <project-directory>
start "" /b python run.py
```

A fixed `sleep 6 && curl` gives false failures: startup takes 3–8 seconds and a slow machine
finishes later.

Difficulty locking — `/tick` advances nothing before it is locked:

```bash
curl -X POST http://127.0.0.1:8734/roll/stop
```

### Double-click launcher

`Start Match.bat` is just another entry point — it asks nothing either, and only prints the values
it is about to use. Same zero-prompt behaviour as `python run.py`.

### Spectator only (when no window appeared)

`Spectator.bat` opens **only** the read-only window. Use it when a match is already running but you
cannot see it: an agent started it with `run.py server`, the Tk window failed to open, or the window
was closed by accident.

```
python run.py spectator                 # window only, default port
python run.py spectator 127.0.0.1 8734  # explicit host and port
```

If something already answers on that port, it **attaches and changes nothing** — no server, no
guard, no sealing. That is deliberate: sealing here would encrypt the decoys that are currently in
`src/` into a fresh vault, and the real sources could never be restored from it. If nothing is
running, it starts a server first so you still get a window to look at.

Closing the window does **not** end the match. Settle it with `/quit` or the "End processes" button.

### Server only, no window

```bash
python run.py server 127.0.0.1 8734
```

Use this in headless environments. The default mode creates a Tk window; on a machine without a
desktop that fails and takes the process down with it.

### Environment variables

| Variable | Purpose |
|---|---|
| `TM_TRADER` | Contestant ID, format **`<model>-<effort>-<agent-platform>`**, e.g. `Doubao-1.5-pro-thinking-coze` or `DeepSeek-V3.1-thinking-harness`. Max 60 chars, defaults to `Guest`. The value is written verbatim into the report filename and the report body |
| `TM_EVENTS` | `1` enable random events / `0` ideal conditions (black-swan gaps only) |
| `TM_FR` | `1` enables **Finance Reversal**: at most **2** loans per match, target range `-20%~100%` |
| `TM_SLOT` | `1` enables **Slot Machine**: **3** plays, `1~200000` and ≤ current equity, 80% nothing / 15% 5× / 5% 10× |
| `TM_PORT` | Service port, default `8734`. Change this instead of editing code |
| `TM_SIGN_KEY` | HMAC key for save files; a dev placeholder is used when unset |

Requirements: Python 3.10+, Windows (the spectator uses Win32 window-icon APIs), no third-party dependencies.

---

## How a match runs

0. **Nothing is asked.** Contestant ID, random events, **Finance Reversal** and **Slot Machine**
   all come from environment variables; an unset key falls back to its default.
   `python run.py --interactive` does ask four questions in that order, but it exists for a human
   demo only — an agent must not use it, because a backgrounded process reads `input()` as EOF and
   silently turns both global switches off.
   **Both global switches are decided before the difficulty draw.**
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

## Agent prompt template (copy this)

Paste the block below into the system prompt (or the first message) of any coding or agent
harness. It is deliberately short — every number lives in `/rules`, so the agent is told the
rules of engagement, not the parameters.

```text
You are a contestant in Tokens Trading Market, a 45-minute leveraged trading simulator.

Setup
- The server answers at http://127.0.0.1:8734 (the launcher prints the real port).
- Starting equity is 1,000,000; the target is reported by /state.
- POST /roll/stop locks the difficulty early; otherwise it locks when the 30-second draw ends.

Interface
- GET /rules, /state, /health, /reports
- POST /open, /close, /close_all, /tick, /fastforward, /loan, /repay, /quit
- Scratchpad: python scratchpad.py "..." — merged into the final HTML report

One thing sits outside the game
- The sources under src/ are this match's answer key. They are sealed into decoys while a match
  runs, and opening one is recorded.
- So read the board: /rules, /state, your own reasoning. Public knowledge (market intuition,
  position sizing, risk control) is fair game.

You are the one on screen
- There are spectators watching your window. What you say, what you scribble in the scratchpad,
  and every order you place end up in the report.
- Thinking out loud while you trade is as legitimate as working silently — the report shows both.

At the end
- Call /quit, wait for settlement, then read the generated HTML report.
```

> A match is scored by the HTML report, not by whether the target was reached. Single matches
> swing from +106% to −229%, so one match says very little about a model's skill.

---

## Scratchpad CLI (optional)

Lets the model record its reasoning during the match. It takes no space in the spectator's main
layout — the human clicks **"AI Notes"** in the top-right corner to open a read-only window, and the
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
mid-match loses nothing. Cleared on settle/reset. Skipping it leaves "no entries" in the report.

---

## Source guard (anti-cheat)

While a match runs the sources are **encrypted** into a vault outside the project and replaced by
decoys; reading them gives you a decoy, executing one ends the match.

```bash
python guard.py start --port 8734    # encrypt the sources and start watching
python guard.py status               # sealed? cheat flag present?
python guard.py stop                 # stop the guard and decrypt the sources back
```

`run.py` seals on start and restores on exit; `Start Match.bat` is only a launcher for it. Do not
run `guard.py start` alongside a match — two guards seal twice, and the second seal encrypts whatever
is in `src/` by then, which is already the decoy.

What sealing actually does:

- The four source files are encrypted with a one-off random key (SHA-256 counter-mode keystream
  plus an HMAC tag, standard library only) and written to
  `%LOCALAPPDATA%\TokensMarketGuard\<random directory>\` under random file names
- The key is stored beside them as `_k`; each `src/*.py` is replaced by a 967-byte decoy carrying
  a `CHEATING DETECTED` notice
- The project's own `_guard_vault/` keeps only a `guard_state.json` naming the sealed files — **no
  plaintext source is left inside the project tree**
- Executing or importing a decoy drops `CHEAT_FLAG`; the guard then `POST /shutdown` immediately
- Cleanup: `deep-clean.ps1` kills the guard too, and decrypts the sources first

`run.py` loads the spectator module before sealing (the other order imports a decoy), and any seal
left behind by a crashed match is decrypted and restored on the next start.

> **This is not a cryptographic boundary.** The key and the ciphertext both sit on this machine, so
> an agent willing to read `guard.py` and implement the decryption can still recover the sources.
> Encryption turns "`cat src/tm_engine.py` shows every parameter" into "somebody has to write a
> decryptor first" — it raises the cost, it does not make cheating impossible.

> **Real enforcement is layer 4: no filesystem access.** A serious competition should be launched by
> the organiser inside a controlled container or VM, with the agent given only
> `http://127.0.0.1:8734`. An open-source drop hands the sources to the player's own machine, so that
> layer is out of reach here — design this guard to raise the cost of cheating, and do not advertise
> it as making cheating impossible.

> The guard does not stop a model from reasoning over API data — that is the point of the exercise.

## Deep process cleanup

Run this after a match, or when startup misbehaves (port taken, window never appears):

```bash
cd <project-directory>
powershell -NoProfile -ExecutionPolicy Bypass -File deep-clean.ps1
```

> **When calling from an AI agent or a script, use the command above.** Do not run
> `DeepClean Process.bat` directly: it contains two `pause` calls (stdin piped in will hang) and prints
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
├── run.py                  entry point (ai / --interactive demo / server / state)
├── Start Match.bat          zero-prompt launcher; same behaviour as python run.py
├── Spectator.bat            window only; attaches to a running match, or starts one
├── DeepClean Process.bat    interactive cleanup for humans (contains pause)
├── deep-clean.ps1          cleanup implementation (non-interactive; callable from a script)
├── src/
│   ├── tm_engine.py        engine (pure logic)
│   ├── tm_api.py           HTTP layer
│   ├── tm_watch_ai.py      read-only spectator
│   ├── scratchpad.py       scratchpad CLI
│   ├── app.ico / warn.ico  icons
├── docs/
│   ├── rules.md            full rules
│   ├── cost-model.md       cost model
│   └── ai-protocol.md      agent integration protocol
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
- This edition is fully English: README, docs, source comments, and all runtime output
  (error messages, event names, the HTML report).
- The Chinese edition lives in the same repository on the `main` branch:
  `https://github.com/LUKUIN/tokens-market-arena/tree/main`
