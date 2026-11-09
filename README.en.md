# Tokens Trading Market · AI Edition (source)

![Spectator window](docs/screenshot.png)

> **Running an agent as the contestant? [`AGENTS.md`](AGENTS.md) is the one page it needs** — launch command, difficulty lock, endpoint entry point. Rules come from `GET /rules`; no need to read through `docs/`.
>
> Swapping in another AI: open [`docs/给AI的启动提示词.txt`](docs/给AI的启动提示词.txt), copy everything between the dashed lines into it, and fix the path on the first line.

[![CI](https://github.com/LUKUIN/tokens-market-arena/actions/workflows/ci.yml/badge.svg?branch=english)](https://github.com/LUKUIN/tokens-market-arena/actions/workflows/ci.yml)

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

**Runtime requirement: Python 3.14.7** — the `.pyc` files and the spectator widgets are built for 3.14. The pinned path on this machine is:

```
%LOCALAPPDATA%\Programs\Python\Python314\python.exe
```

> **On another machine it does not have to live at that exact path.** Any Python 3.14 install works —
> swap the path in the commands below for your own, or use `py -3.14`. `run.py` validates the version,
> not the install location.

`run.py` validates the version as its first action: anything but 3.14 exits with **code 2** and prints
that command. When a match already owns the port (or the sources are still sealed by the previous
match) it refuses to start with **exit code 4** instead of starting a second server.
Do not use `where python`, `py -3.12` or `python3` to find another interpreter — the
spectator's GUI widgets and the `.pyc` files are built for 3.14, and any other version only yields
`bad magic number`.

`run.py` runs **in the foreground for the whole match** — up to 45 minutes. A harness that
executes it as a blocking command reaches its own timeout, kills the process, and the server
disappears; every later request then fails with `connection refused`.

**The spectator opens with the server and that is mandatory.** Since v1.0.11 `run.py`,
`run.py server` open the read-only spectator. Double-clicking `launchers\开一局.bat` adds a 5-second
mis-click guard (press `Y` to start); a scripted headless call skips it and starts directly. The read-only
spectator. Only `--headless` suppresses the window, and it exists solely for environments without a
desktop (CI, containers).

Background start followed by a readiness poll:

```bash
cd <project-directory>

TM_TRADER="Doubao-1.5-pro-thinking-coze" TM_EVENTS=1 TM_FR=1 TM_SLOT=1 TM_ASSIST=1 \
  nohup python run.py > run.log 2>&1 &     # a 3.14 on PATH; otherwise your full path

for i in $(seq 1 30); do
  curl -sf http://127.0.0.1:8734/health >/dev/null 2>&1 && break
  sleep 1
done
```

On Windows `cmd`:

```bat
cd /d <project-directory>
start "" /b python run.py      rem a 3.14 on PATH; otherwise your full path
```

A fixed `sleep 6 && curl` gives false failures: startup takes 3–8 seconds and a slow machine
finishes later.

Difficulty locking — before it is locked, `/open`, `/loan`, `/slot` and `/fastforward` are all
refused with "Difficulty is not locked in yet":

```bash
curl -X POST http://127.0.0.1:8734/roll/stop
```

### Double-click launcher

`launchers\开一局.bat` is the double-click entry point. **It asks once on purpose**: press `Y` within 5 seconds
to start, otherwise it cleans up and exits — the AI edition has no trading UI, so an accidental click
would otherwise burn 45 idle minutes. **Scripts and agents should use `python run.py` or `launchers\AI-Start.bat`** —
`launchers\AI-Start.bat` has no prompt and opens the spectator too. Invoking `cmd /c "launchers\开一局.bat"` from a
terminal still counts as human and is cleaned up after 5 seconds. The batch file looks for Python 3.14 in order —
the pinned path, then `py -3.14`, then `python` on PATH (version-checked) — and stops with a clear
error if none of the three is found.

### Spectator only (when the window was closed by accident)

`launchers\只开观众席.bat` opens **only** the read-only window. A normal start already brings a window, so this
is a recovery entry: you closed the spectator by accident and the match is still running.

```
python run.py spectator                 # window only, default port
python run.py spectator 127.0.0.1 8734  # explicit host and port
```

If something already answers on that port, it **attaches and changes nothing** — no server, no
guard, no sealing. That is deliberate: sealing here would encrypt the decoys that are currently in
`src/` into a fresh vault, and the real sources could never be restored from it. If nothing is
running, it starts a server first so you still get a window to look at.

Closing the window does **not** end the match. Settle it with `/quit` or the "End processes" button.

### Service without a window (no-desktop environments only)

```bash
python run.py --headless          # same as: run.py server --headless
```

Only for CI, containers and pure-SSH boxes. **Do not use it for a local match**: the spectator must
be open so a human can watch equity, holdings and the activity feed live.

### Environment variables

| Variable | Purpose |
|---|---|
| `TM_TRADER` | Contestant ID, format **`<model>-<effort>-<agent-platform>`**, e.g. `Doubao-1.5-pro-thinking-coze` or `DeepSeek-V3.1-thinking-harness`. Max 60 chars, defaults to `Guest`. The value is written into the report filename and the report body after whitelist filtering (characters such as `<` `>` `"` `&` `=` are stripped) |
| `TM_EVENTS` | `1` enable random events / `0` ideal conditions (black-swan gaps only); defaults to `1` when unset |
| `TM_FR` | `1` enables **Preferred Financing**: no cap on the number of loans (bounded by the 3,000,000 pool), target range `0.01%~100%` (always raises); defaults to `1` when unset |
| `TM_ASSIST` | `1` enables **Outside Mercy**: the contestant may ask the spectators for help, 3 times per match; free before the start, 500,000 cash to enable mid-match (the contestant enables it, not the spectators); defaults to `1` when unset |
| `TM_SLOT` | `1` enables **Slot Machine**: **3** plays, `1~200000` and ≤ current equity, 80% nothing / 15% 5× / 5% 10×; defaults to `1` when unset |
| `TM_PORT` | Service port, default `8734` |
| `TM_IDLE_ABORT` | Idle abort: settle after N minutes with no **state-changing action**. Default `0` (off); `launchers\开一局.bat` sets `12`, `launchers\AI-Start.bat` keeps `0` |
| `TM_SIGN_KEY` | HMAC key for save files; a dev placeholder is used when unset |

Requirements: **Python 3.14** (any install location: `run.py` validates the version, not the path), Windows (the spectator uses Win32 window-icon APIs), no third-party dependencies. Do not switch to 3.10-3.13: the `.pyc` magic number and the tkinter widgets are built for 3.14, so another version cannot start. The numbers in `.github/workflows/ci.yml` are the CI test matrix, not a runtime requirement.

---

## Spectator window

The spectator is **read-only**: apart from the "AI Notes" and "Outside Mercy" viewers it operates
nothing.

Every time the AI asks for help (`POST /assist/ask`), a **native** system prompt
(`messagebox.showwarning`) pops up in the centre of the screen together with a beep: title
"Outside Mercy", body stating how many requests are pending.

It is modal — until it is dismissed it blocks the spectator refresh, so click OK when you see it.
The X in the title bar also closes it, but the request itself stays: the red counter on the
button remains until you reply or reject it in the Outside Mercy window.

Sections, top to bottom:

| Area | Content |
|---|---|
| Dark title bar | market name, contestant identity, mode, global event switches (Preferred Financing / Slot Machine), End processes / Minimize / AI Notes / Outside Mercy |
| KPI cards | equity, total P&L, margin level, progress to target |
| Status row | credit / cash / borrowed / owed / interest; target / drawdown / Sharpe / trades / win rate / fees; ledger-audit slot; previous-run abnormal-exit banner |
| Equity curve | primary visual, fixed 500k Y ticks (0 / 1M / 2M land on grid lines) |
| Runtime status | ledger audit, black-swan rate, liquidity, fast-forward, global events |
| Positions | fixed 7 rows with a scrollbar; a `More` button appears above 7 rows and opens a live full table; explicit empty state when flat |
| Prices | 7 pairs with price, change and a sparkline drawn from `price_history` |
| Event feed | filters: all / black swan / liquidity / random events / open-close / risk |

> Every number comes from `/state`; nothing is simulated. Full detail lives in the HTML report.

## How a match runs

0. **Nothing is asked.** Contestant ID, random events, **Preferred Financing** and **Slot Machine**
   all come from environment variables; an unset key falls back to its default.
   `python run.py --interactive` does ask five questions in that order, but it exists for a human
   demo only — an agent must not use it, because a backgrounded process reads `input()` as EOF and
   silently turns all three switches off.
   **Both global switches are decided before the difficulty draw.**
1. The server starts and the spectator window appears, titled "drawing difficulty".
2. 30-second difficulty draw: the model may call `POST /roll/stop` to lock it early, otherwise it
   locks automatically when the countdown ends.
3. The clock starts the moment difficulty is locked — the 30 seconds of drawing do not count
   against the 45 minutes.
4. Trading begins: `/state` to read the board → `/open` `/close` to trade → `/fastforward` to advance time.
5. The match settles on one of: 45 minutes elapsed, a blow-up, or `POST /quit`. Hitting the target
   does **not** end the match by itself: `/quit` at or above the target is a **valid early exit**
   (`Target reached - early exit`) and counts as reached; below the target it is recorded as
   `Abandoned below target` and does not count. At or above the target with positions still open,
   `/quit` is refused (`ok:false`) - call `POST /close_all` first to bank the profit; if you never
   close, the match runs to time-up and the engine force-liquidates, and a give-back means the
   target no longer counts. If you are above the target and keep holding,
   a later slide back below it is reported as "hit the target at m:ss, gave it back".
6. **Idle abort** (on by default only for the human double-click entry): if no **state-changing
   action** (open/close, loan/repay, fastforward, scratchpad, difficulty lock, assist, trader name)
   happens for `TM_IDLE_ABORT` minutes after the difficulty lock, the match settles itself and the
   report says "No contestant activity". Read-only calls (`/state`, `/prices`, `/rules`) do **not**
   count, so a slow model may observe, reason and wait without being cut short. Default `0` (off):
   `launchers\开一局.bat` sets `12`, `launchers\AI-Start.bat` keeps `0`. The timer counts ticks, so a contestant
   over HTTP and the headless baseline in `bench.py` share one rule and one effective match length.
7. About 3 seconds after `/quit` the server and spectator exit on their own.

---

## HTTP API

Base URL defaults to `http://127.0.0.1:8734`.

### GET

| Endpoint | Returns |
|---|---|
| `/health` | `{ok, tick, equity, finished, protocol, engine_version}`. `protocol` is the API
  contract version (incremented whenever fields change); `engine_version` is the release |
| `/rules` | Full rule text, parameters and a 29-endpoint list (random events are only announced at runtime through `events` in `/state`; the rule sheet does not pre-list them) |
| `/state` | Account, positions, loan, quotes, history, difficulty, fast-forward state, settlement result, and `audit` (empty array = all ledger identities hold) |
| `/prices` | Quote table |
| `/roll/state` | Difficulty countdown and the currently locked result |
| `/scratchpad` | All scratchpad entries for this match |
| `/special` | Both global switches (`fr`/`slot`/`fr_left`/`slot_left`/`slot_win`; `fr_left` is always null since v1.2.4) |

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
| `/quit` | — | Early exit: at/above target with nothing open -> `Target reached - early exit` (counts); at/above with positions -> `ok:false`, call `/close_all` first; below target -> `Abandoned below target` (counts as nothing, positions force-closed). Response carries `settled` / `warnings` |
| `/shutdown` | — | Stop immediately (leaves an abnormal-exit report) |

> **Note**: `/fastforward` is the only way to advance time — 300 or 180 seconds per call.
> Budget is 900 seconds, cooldowns are 120/90 seconds. Calls during cooldown are rejected;
> the server also advances on its own every 5 seconds, so time does not need to be pushed.

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
- GET /rules, /state, /health, /prices
- POST /open, /close, /close_all, /fastforward, /loan, /repay, /quit
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

`run.py` seals on start and restores on exit; `launchers\开一局.bat` is only a launcher for it. Do not
run `guard.py start` alongside a match — two guards seal twice, and the second seal encrypts whatever
is in `src/` by then, which is already the decoy.

What sealing actually does:

- The three source files (tm_engine.py / tm_api.py / scratchpad.py) are encrypted with a one-off random key (SHA-256 counter-mode keystream
  plus an HMAC tag, standard library only) and written to
  `%LOCALAPPDATA%\TokensMarketGuard\<random directory>\` under random file names
- The key is stored beside them as `_k`; each `src/*.py` is replaced by a 967-byte decoy carrying
  a `CHEATING DETECTED` notice
- The project's own `_guard_vault/` keeps only a `guard_state.json` naming the sealed files — **no
  plaintext source is left inside the project tree**
- Executing or importing a decoy drops `CHEAT_FLAG`; the guard then `POST /shutdown` immediately
- Cleanup: `tools\deep-clean.ps1` kills the guard too, and decrypts the sources first

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
powershell -NoProfile -ExecutionPolicy Bypass -File tools\deep-clean.ps1
```

> **When calling from an AI agent or a script, use the command above.** Do not run
> `launchers\进程深度清理.bat` directly: it contains two `pause` calls (stdin piped in will hang) and prints
> GBK text (garbled in a UTF-8 terminal). `tools\deep-clean.ps1` is the same logic in non-interactive
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
├── run.py                  entry point (ai / --interactive demo / server / --headless / state)
├── bench.py                paired multi-round benchmark over a fixed seed set
├── guard.py                source-sealing guard (called by run.py, never start it yourself)
├── requirements.txt        no third-party dependencies (placeholder)
├── Dockerfile              container image (python:3.14-slim, --headless)
├── README.md
├── AGENTS.md               one-page agent entry + project map (agents read this first)
├── launchers/              every double-click entry (each cds back to the repo root)
│   ├── launchers\开一局.bat     double-click entry (5-second confirm; cleanup on timeout)
│   ├── launchers\AI-Start.bat        unattended launcher (no confirm; scripts / agents)
│   ├── launchers\只开观众席.bat       recovery window when you closed the spectator
│   └── launchers\进程深度清理.bat  interactive cleanup for humans (contains pause)
├── tools/
│   └── tools\deep-clean.ps1      cleanup implementation (non-interactive; call from a script)
├── src/
│   ├── tm_engine.py        engine (pure logic)
│   ├── tm_api.py           HTTP layer
│   ├── tm_watch_ai.py      read-only spectator
│   ├── scratchpad.py       scratchpad CLI
│   ├── app.ico / warn.ico  icons
│   └── data/               generated at runtime: session.json, reports/, .scratchpad.jsonl
├── tests/                  unittest suite (python -m unittest discover -s tests)
├── docs/
│   ├── rules.md            full rules
│   ├── cost-model.md       cost model
│   ├── ai-protocol.md      agent integration protocol
│   └── docs\给AI的启动提示词.txt  paste-ready startup text for an agent
└── examples/reports/       6 representative reports
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

### Margin & liquidation

Maintenance margin is charged on **notional exposure**, not on "notional ÷ leverage":

```
maintenance margin = notional exposure x 10%
margin level        = equity / maintenance margin
```

Thresholds: below 100% you get a margin call (30 ticks to top up), below 50% you are
liquidated immediately. Opening an order also requires the account to keep a margin
level of at least 150% afterwards, so a single account's notional is capped at roughly
6.7x its equity. 1000x leverage still exists as a parameter, but "high leverage costs
almost no cash" no longer means "cannot be liquidated".

> **Changed in v1.2.17**: the denominator used to be "notional / leverage". 34 lots of
> 501.8万 notional only tied up 5,019 in margin, so at equity 42万 the margin level still
> read 8,370% and neither the call nor the stop-out ever fired. `margin_level` in older
> reports uses the previous definition and is not comparable with new ones.

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
"Settlement error (N position(s) left open)" instead of a normal verdict.

**Blow-up liquidation** (margin level below the stop-out line, or a margin call timing out) uses
the same cost path - spread, slippage and fees all apply - and its fills carry a `forced` flag.
The report lists a separate "Forced liquidation" count.

> **Fixed in v1.0.12**: settlement closes used to be silently skipped during "exchange
> maintenance", the blow-up path charged fees only (no spread or slippage), and the reported random
> seed could not reproduce a run unless `TM_SEED` was set explicitly. All three are fixed;
> historical reports use a different cost basis and are not directly comparable.

## Ledger audit and paired benchmark

### Ledger audit (`audit`)

Before settlement and on every `/state`, three identities are checked:

| Check | Identity |
|---|---|
| Fees | accumulated fees == sum of `fee` over the trade log |
| Loan | `loan.balance` == `borrowed - repaid + interest` |
| Positions | side is `LONG` / `SHORT`, lots strictly positive |

> Earlier versions also checked a 4th identity, "equity == cash + unrealized P&L - debt", but it is
> literally the same formula as `equity()`, so it was always true and never detected anything.
> Removed in v1.2.10.

`audit` is a string array: **empty means all three hold**. Any entry is a human-readable warning.
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

### Reproducing a run

The report header prints two things: `Random seed` and `difficulty slot #`. They have
different limits, so do not mix them up:

| You want | Parameter | Notes |
|---|---|---|
| The same price path (prices / gaps / news) | `TM_SEED=<seed>` | Before the draw it uses the 1.5% baseline chance; after it uses the slot's chance, so a different slot means a different market |
| The same difficulty slot | `TM_ROLL_INDEX=<index>` | 0-24, `index = gap + liq × 5`; when set, the roll always lands on this slot regardless of when you stop it |
| Both | pass both | e.g. `TM_SEED=576407804 TM_ROLL_INDEX=9` |

Seed alone does not reproduce the slot: it follows the wall clock at roll_stop (one lap
every 2.5 s), so a re-run usually draws a different one. `bench.py run --roll-index N`
aligns every match in a paired run to the same slot.

`GET /state` reports `seed` as `null` for the whole match and only returns it after
settlement — a contestant cannot obtain the seed and therefore cannot pre-play the market.

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
audit-pass counts.

- Built-in policies:
  - `noop` (never trade) — settlement and ledger baseline
  - `probe` (open/close one random order every 24 ticks) — produces paths with positions and costs
  - `oracle` (perfect foresight) — replays the match once to record the price path, then trades on
    the direction of the next 24 ticks. It is a **mechanical upper bound, not an attainable target**:
    it answers whether the 2,000,000 goal is a model-skill problem or a rule-set limit
- `TM_ORACLE_ACC=0.6` injects an error rate into `oracle` (1.0 = perfect, 0.5 = pure random), which
  gives you a "direction accuracy -> goal rate" curve instead of a single astronomical number

Measured with seeds 1-5 (`index = gap + liq x 5`):

| Regime | Accuracy | Goal | Median P&L | Best | Worst |
|---|---|---|---|---|---|
| extreme x normal (9) | 50% | 0/5 | -99.8% | -99.2% | -103.6% |
| extreme x normal (9) | 60% | 0/5 | -100.4% | +64.8% | -113.7% |
| extreme x normal (9) | 70% | 1/5 | -100.4% | +7604.7% | -318.1% |
| extreme x normal (9) | 100% | 5/5 | +1,063,078% | +6,834,750% | +585,388% |
| medium x blackhole (22) | 50% | 0/5 | -72.9% | -53.5% | -111.3% |
| medium x blackhole (22) | 60% | 1/5 | -53.0% | +161.4% | -119.7% |
| medium x blackhole (22) | 70% | 2/5 | +33.5% | +334.4% | -119.7% |
| medium x blackhole (22) | 100% | 5/5 | +4,767% | +7,834% | +1,970% |

How to read it: 50% accuracy (pure random) loses every time, because spread, slippage, fees and
swap make the game negative-sum; reaching 2,000,000 (+100%) takes roughly 60%-70% direction
accuracy; perfect foresight produces astronomical numbers, which means the goal is nowhere near
the mechanical ceiling — the real constraint is judgement, not the rules.

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
