# Game Rules

> Derived from the packaged AI edition rules. Parameters are identical to the Human edition; only
> the way you operate differs.

## Starting up

The runtime requires **Python 3.14** (`.pyc` and the spectator widgets are built for 3.14).
**Any install location works**: `run.py` validates the version, not the path. On this machine it is usually:

```
%LOCALAPPDATA%\Programs\Python\Python314\python.exe
```

**Every `python` in the commands below means that absolute path.** `run.py` validates the version
itself too and exits with code 2 when it does not match.

```bash
set TM_TRADER=Doubao-1.5-pro-thinking-coze
set TM_EVENTS=1
python run.py
```

**Idle abort**: with no **state-changing action** for `TM_IDLE_ABORT` minutes after the difficulty
lock, the match settles itself and the report says "No contestant activity". It exists for accidental
starts — the AI edition has no trading UI. Read-only calls (`/state`, `/prices`, `/rules`) do not
count, so slow thinking is never cut short. **Default `0` (off)**: `launchers\开一局.bat` sets `12`,
`launchers\AI-Start.bat` keeps `0`; the timer counts ticks, matching the headless baseline in `bench.py`.

The server listens on `127.0.0.1:8734`; the GUI is a read-only spectator. **Nothing is prompted.**
Every parameter comes from the environment, and anything unset falls back to a default
(`TM_TRADER=Guest`, `TM_EVENTS=1`, `TM_FR=1`, `TM_SLOT=1`, `TM_ASSIST=1`). Startup order: read the environment →
server starts → difficulty draw (30 s, lock early with `POST /roll/stop`) → **locked in** → clock starts →
the model trades over HTTP.

> **Nothing works before the lock-in**: opening a position, borrowing, slot bets and fast-forward
> all return "Difficulty is not locked in yet". Everything unlocks the second the draw ends;
> no extra call is needed.

> `TM_TRADER` is written into the report filename and the report body after whitelist filtering; it is the field that
> tells contestants apart.
> For a manual demo, `python run.py --interactive` asks for the player name, random events,
> **Preferred Financing** and **Slot Machine** in that order.

You can also double-click `launchers\开一局.bat` — it asks once: press `Y` within 5 seconds, otherwise it cleans up and exits.

> This document covers the **AI edition**. The Human edition (`TokensMarket-OpenSource-Human`) has
> an investment panel; its rule parameters are the same as here.

---

## Difficulty

Difficulty has two dimensions, drawn at the start, five tiers each. They govern two different
things:

- **Black Swan** — how often risk hits
- **Liquidity** — how large a position you dare to hold

### Black Swan · gap probability per pair per tick

| Tier | Chance | Expected gaps per pair in 45 min |
|---|---:|---:|
| Very low | 0.24% | ~1.3 |
| Low | 0.60% | ~3.2 |
| Medium | 1.50% | ~8.1 |
| High | 3.75% | ~20 |
| Very high | 9.38% | ~51 |

Gaps run 2%–12%, direction random. A resting stop can be skipped outright — placing a stop at 126.5
and filling at 131 is common.

### Liquidity · slippage cost

| Tier (market depth) | 10M notional round trip | % of 1M principal |
|---|---:|---:|
| Ample (32M) | 17,500 | 1.75% |
| Normal (16M) | 25,000 | 2.50% |
| Thin (8M) | 40,000 | 4.00% |
| Drained (4M) | 70,000 | 7.00% |
| Black hole (2M) | 130,000 | 13.0% |

The table is 10M notional at an AURA-grade spread (0.06%) and includes commission (4,000),
spread (6,000) and slippage. **It is cost as a share of the 1M starting principal**, not of notional.

**Slippage grows with the SQUARE of notional**: cost = `SLIP_K / (2 × market depth) × notional²`,
`SLIP_K = 0.0024`. Doubling the notional quadruples the slippage cost. One-sided slippage is capped
at 1.4% (6% during a liquidity shock).

**End-game markup (v1.2.0)**: from `tick >= 360` (the last 15 minutes) the slippage multiplier climbs linearly to `1.5` at `tick = 540`. It gives nothing away -- quitting at tick 0 still returns 0 -- it just makes staying late more expensive.

Difficulty is shown in the window title:

```
Tokens Trading Market | your name (ideal conditions) | Black Swan: low | Liquidity: thin
```

---

## Global switches: Preferred Financing and Slot Machine

These are **not** random events. They are global switches chosen at the start, effective for the
whole match. They can only be decided at the start.

- Enabling at start: **free**
- **Once the match begins they can no longer be turned on** (turning one off is always free)

### Preferred Financing

When enabled:

- **Unlimited** loans per match (still bounded by the 3,000,000 pool and the remaining borrowing limit); the only concession is the target-uplift floor dropping from +1% to +0.01%
- Target-uplift range: `+1% ~ +100%` becomes `+0.01% ~ +100%` (**it always goes up, never reduces the target**; minimum 0.01%)
- The uplift grows with cumulative borrowing: first 300k is about 4%-8%, a full 3M in one go is about 35%-66%
- Splitting a loan into ten parts costs exactly the same as borrowing it all at once

Example: target 2M, borrow 300k and draw +6% -> new target = 2M + 18k = **2.018M**

When disabled: unlimited loans, uplift always `+1% ~ +100%` (also cumulative).

### Slot Machine

When enabled:

- **3 plays** per match, `1 ~ 200,000` per play, never above your current equity at bet time
- **80%** nothing / **15%** refund 5× / **5%** refund 10×
- Winnings go to cash; the target also rises by `-5% ~ 100%` of the winnings

### Combined target formula

```
Total = original target
      + sum over loans of amount × pct     ← pct rises with cumulative borrowing
      (first 300k ~4%~8%, borrowing the whole pool ~35%~66%;
       integrated over the cumulative amount, so splitting costs the same)
      + total slot winnings × U(-5%~100%)  ← Slot Machine on
```

The two increments are drawn independently. If only one switch is on, only that term applies.

Calling either after its uses run out returns `This run has used all of them; refused` (uses exhausted, refused).

---

## Fast-forward

Each match gives **15 minutes (900 seconds)** of fast-forward budget. The two tiers can be mixed freely:

| Tier | Each step | Cooldown after |
|---|---:|---:|
| 5 minutes | 300 s | 120 s |
| 3 minutes | 180 s | 90 s |

- The 30-second difficulty draw does not count against the 45 minutes — the clock starts when you lock in.
- The cooldown matches the tier you just used.
- During cooldown `POST /fastforward` returns `ok: false`; `ff.cool_left` gives the seconds left.
- If the remaining budget cannot cover a tier, that jump does not execute.
  Example: used `5′+3′+3′+3′ = 840 s`, 60 s left — neither tier is usable.
- Budget and cooldown live in the `ff` field of `GET /state`: `used` / `remain` / `cool_left` / `can5` / `can3`.
- Time advances one way only: fast-forward. 900 s per match, 300 or 180 s per step, 120/90 s cooldown — it cannot be bypassed.

### What the spectator window can do

The AI edition's spectator is **read-only**: no order buttons, no fast-forward button, and no "settle" button. The window offers exactly two actions:

| Action | Effect |
|---|---|
| Minimize | Hides the window; the match keeps running |
| End processes | Stops the server and closes the window — **counts as one abnormal exit** |

End a match normally with `POST /quit` (settles and writes the report); do not use "End processes" for that.
At or above the target with positions still open, `/quit` is refused (`ok:false`, positions listed) -
call `POST /close_all` first. If you never close, the match runs to time-up and is force-liquidated.

---

## FAQ

**Q: Double-clicked the bat and it sits at "drawing difficulty"?**
A: That is the 30-second countdown; `POST /roll/stop` freezes it early.

**Q: The window never appears?**
A: You are still in the difficulty draw or the rules window — check whether another window covers it.

**Q: Where is the report?**
A: One `.html` file per match under `src/data/reports/`. Its header carries the random seed
and the difficulty slot index; to replay a match exactly, restart with
`TM_SEED=<seed> TM_ROLL_INDEX=<index>` (the seed alone does not pin the slot).

**Q: How do I start over?**
A: `POST /reset` (30-second cooldown). The AI edition has no investment panel and no "restart match" button.

**Q: Windows warned and blocked the file?**
A: The source edition has no `.pyd`; only the `.bat` may be blocked by SmartScreen.
Right-click the bat → Properties → tick "Unblock" → OK. Once is enough.

---

## Challenge tasks (a port of PvZ2 Level Objectives)

Once the difficulty roll is fixed the engine does not start trading right away: it first asks
**does this round run with challenge tasks?** Answer with `POST /challenge/accept` or
`POST /challenge/decline` within 75 seconds; no answer means "off".

Enabling draws **3 objectives** that stay fixed for the whole round. Judging runs live:
breaking an objective marks it × permanently, meeting one marks it √ immediately.

### Objective pool

| Objective | How it is judged | Tiers (low / medium / high difficulty) |
|---|---|---|
| No Borrowing | Never borrow from the loan pool | — |
| No Blow-up | Never get force-liquidated | — |
| Self-reliant | Never use the Crowd's Mercy | — |
| No Locked Pairs | Never hold long and short on the same pair | — |
| Fee Discipline | Cumulative fees stay under X of capital | 1.5% / 1.0% / 0.7% |
| Drawdown Guard | Max equity drawdown stays under X | 18% / 12% / 8% |
| Light Footprint | Never hold more than X pairs at once | 4 / 3 / 2 |
| Margin Cushion | Margin level never drops below X while holding | 150% / 180% / 220% |
| Patience Pays | Close at least X position(s) held for 5 ticks | 1 / 2 / 3 |
| Beat the Target | Final equity reaches X of the target | 120% / 150% / 200% |
| Double or Nothing | Final equity reaches the current target (doubled when drawn) | Target x2; slot and loan target bumps fixed at 50%-100% |

Drawing rules:

- **At least one result-type objective** (Patience Pays / Beat the Target / Double or Nothing) is always included:
  three "do not do X" titles would reduce the round to doing nothing
- The three are distinct; Double or Nothing and Beat the Target are mutually exclusive
  (the target is already doubled, stacking 200% would make it 4x and the round a certain loss)
- Thresholds follow the difficulty tier: `tier = max(black-swan tier, liquidity tier)`,
  0-1 uses the loose column, 2 the medium one, 3 the strict one

### Three states

| Mark | Meaning |
|---|---|
| √ | cleared (result-type objectives can clear early and then stop changing) |
| × | broken (a process objective is failed permanently once violated) |
| · | in progress |

End-of-round settlement closes every objective: process objectives that were never violated are
recorded as cleared; result objectives still short of their goal are recorded as failed.

The spectator window's "Challenge Tasks" card shows each objective's name, exact rule,
current state and the reason it broke; the event feed records entries prefixed
`[Challenge]`. When the contestant declines, the card reads
"The contestant did not enable challenge tasks".

Three boundaries:

- **The answering window does not eat the 45 minutes**: the clock is rebased when you answer (or time out)
- **A broken objective never recovers**: once ×, it stays ×
- **Settlement is untouched**: challenge tasks are optional extra rules; target equity, cash settlement and the report are unchanged

## Huge Wave warning (a special event)

One shape of random event stands apart: it fires **0 to 3 times per session**, and the
count is rolled, not fixed. At session start the engine draws once from four equal tiers -
0, 1, 2 or 3 times at 25% each. Nothing fires during the first 2.5 minutes.
Two Huge Waves are at least 3 minutes (36 ticks) apart. That is a **cooldown**, not a fixed
metronome: once it expires the trigger stays random at 1% per tick, so it may fire right
away or much later. In the final 3 minutes the engine falls back to a 100% trigger and
spreads whatever is left evenly over the remaining time, so every drawn wave fires
before the 45 minutes end.


When it does fire it runs in three stages, timed after Plants vs. Zombies' "a huge wave of
zombies is approaching":

| Stage | What happens | Duration |
|---|---|---|
| 1. Warning | A red banner snaps open in the dead centre of the spectator window reading "A HUGE WAVE OF VOLATILITY IS APPROACHING!" while the original Plants vs. Zombies horn sample plays; the event feed records one `kind=huge_wave` entry | instant |
| 2. Hold | **No ordinary news is drawn at all**, though prices keep moving. These two ticks are your window to cut exposure or hedge | 2 ticks = 10 s |
| 3. Burst | 3-5 shock events land at once (flash crash, Swiss franc moment, chained gaps, liquidity drought ...), all taking effect in the same tick | instant |

Three boundaries worth knowing:

- **It announces arrival, never direction or size** - the banner will not tell you whether
  it is bullish or bearish. That judgement is yours.
- **The burst pool contains no tailwind events** - "ample liquidity" and "market makers
  return" cannot be drawn into it. That is deliberate, not an omission.
- **The warning itself changes nothing** - all the damage is in the third stage. The silent
  second stage is not a cushion, it is the countdown.

## Platform-restriction events (random)

| Event | Duration | Blocks | Exception |
|---|---|---|---|
| Risk review | 5 minutes | Borrowing | The 60-second self-rescue window while cash is negative still works |
| Exchange maintenance | 5 seconds (1 tick) | Closing positions yourself | Blow-up liquidation and end-of-match settlement still work |
| Slot maintenance | 8 minutes | Slot bets | — |

All three fire at random. The system will not skip them because you happen to be mid-action.

---

This program is for entertainment and learning only. Nothing here relates to a real market.

## Outside Mercy

A two-way channel between the contestant and the spectators. **On by default** (`TM_ASSIST` unset counts as `1`, matching `TM_EVENTS` / `TM_FR` / `TM_SLOT`; set `TM_ASSIST=0` to disable).

- **Before the match**: already on and free; set `TM_ASSIST=0` to turn it off. The interactive prompt can also switch it.
- **After the start**: mid-match enabling was removed in v1.2.23 — `POST /assist/enable` now only returns an error. (Legacy note: it used to deduct **500,000** cash.)
  is short.
- The spectator window has no enable control: whether to enable this is the contestant's decision alone.

Once enabled:

| Endpoint | Purpose |
|---|---|
| `POST /assist/ask` `{"text": "..."}` | The contestant asks the spectators. **3 per match**; beyond that it returns `no asks left (3/3)`. Returns a `ticket` |
| `GET /assist/inbox` | Collect whatever the spectators said that has not been collected yet; items are delivered once |
| `POST /assist/reply` `{"ticket": "a1", "text": "..."}` | Spectators answer one ask |
| `POST /assist/reject` `{"ticket": "a1"}` | Spectators decline one ask |
| `GET /assist/pending` | What the spectator GUI polls: unanswered asks plus the full log |

**Asking does not block.** `POST /assist/ask` returns immediately; the contestant keeps trading and
decides for itself when to check `GET /assist/inbox`.

While an ask is pending, the GUI button turns red with a count and plays one system beep. The whole
exchange is merged into the report's "Outside Mercy" section.

> Spectators can only reply with text; opening and closing positions still has to go through the
> contestant's own API calls.
