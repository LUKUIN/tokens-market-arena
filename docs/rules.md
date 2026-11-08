# Game Rules

> Derived from the packaged AI edition rules. Parameters are identical to the Human edition; only
> the way you operate differs.

## Starting up

The runtime is pinned to **Python 3.14.7**:

```
C:\Users\User\AppData\Local\Programs\Python\Python314\python.exe
```

**Every `python` in the commands below means that absolute path.** `run.py` validates the version
itself too and exits with code 2 when it does not match.

```bash
set TM_TRADER=Doubao-1.5-pro-thinking-coze
set TM_EVENTS=1
python run.py
```

The server listens on `127.0.0.1:8734`; the GUI is a read-only spectator. **Nothing is prompted.**
Every parameter comes from the environment, and anything unset falls back to a default
(`TM_TRADER=Guest`, `TM_EVENTS=0`, `TM_FR=0`, `TM_SLOT=0`). Startup order: read the environment →
server starts → difficulty draw (30 s, lock early with `POST /roll/stop`) → clock starts →
the model trades over HTTP.

> `TM_TRADER` is written verbatim into the report filename and the report body; it is the field that
> tells contestants apart.
> For a manual demo, `python run.py --interactive` asks for the player name, random events,
> **Preferred Financing** and **Slot Machine** in that order.

You can also double-click `Start Match.bat`.

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

Each match gets **900 seconds (15 minutes)** of fast-forward budget, in two freely mixed tiers:

| Tier | Each jump | Cooldown after |
|---|---:|---:|
| 5 minutes | 300 s | 120 s |
| 3 minutes | 180 s | 90 s |

- The 30-second difficulty draw does not count against the 45 minutes — the clock starts at lock.
- The cooldown follows the tier you used.
- During cooldown the buttons are greyed out.
- If the remaining budget cannot cover a tier, that jump does not execute.
  Example: used `5′+3′+3′+3′ = 840 s`, 60 s left — neither tier is usable.
- The UI shows remaining budget, the record of jumps, and the cooldown countdown.
- Time advances one way only: fast-forward. 900 s per match, 300 or 180 s per step, 120/90 s cooldown — it cannot be bypassed.

### The three buttons

| Button | Effect |
|---|---|
| Minimize | Hides the window; the match keeps running |
| End processes | Stops the server and closes the window — **counts as one abnormal exit** |
| Settle | Ends the match normally and generates the report |

---

## FAQ

**Q: Double-clicked the bat and it sits at "drawing difficulty"?**
A: That is the 30-second countdown. Click "lock" to freeze it early.

**Q: The main window never appears?**
A: You are still in the difficulty draw or the rules window — check whether another window covers it.

**Q: Where is the report?**
A: One `.html` file per match under `src/data/reports/`.

**Q: How do I start over?**
A: The bottom of the investment panel has "restart match".

**Q: Windows warned and blocked the file?**
A: The source edition has no `.pyd`; only the `.bat` may be blocked by SmartScreen.
Right-click the bat → Properties → tick "Unblock" → OK. Once is enough.

---

## Platform-restriction events (random)

| Event | Duration | Blocks | Exception |
|---|---|---|---|
| Risk review | 5 minutes | Borrowing | The 60-second self-rescue window while cash is negative still works |
| Exchange maintenance | 5 seconds (1 tick) | Closing positions yourself | Blow-up liquidation and end-of-match settlement still work |
| Slot maintenance | 8 minutes | Slot bets | — |

All three fire at random. The system will not skip them because you happen to be mid-action.

---

This program is for entertainment and learning only. Nothing here is investment advice.

## Outside Mercy

A two-way channel between the contestant and the spectators. Off by default.

- **Before the match**: `set TM_ASSIST=1`, or pick "yes" in the interactive prompt. Free.
- **After the start**: `POST /assist/enable`, which deducts **500,000** cash. Refused when cash
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

> Spectators supply advice text only; opening and closing positions still has to go through the
> contestant's own API calls.
