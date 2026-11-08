# Game Rules

> [中文](rules.md) · **English**

> Derived from the packaged AI edition rules. Parameters are identical to the Human edition; only
> the way you operate differs.

## Starting up

The runtime is pinned to **Python 3.14.7**:

```
C:\Users\User\AppData\Local\Programs\Python\Python314\python.exe
```

**Every `python` below means that absolute path.** `run.py` also validates the version itself and
exits with code 2 on a mismatch.

```bash
set TM_TRADER=<model>-<effort>-<agent-platform>
set TM_EVENTS=1
python run.py
```

The server listens on `127.0.0.1:8734`; the GUI is a read-only spectator. Startup order:
player name → random events on/off → **Preferred Financing** switch → **Slot Machine** switch →
server starts → difficulty draw (30 s, lock early with `POST /roll/stop`) → clock starts →
the model trades over HTTP.

> Both global switches are decided after the events question and before the difficulty draw.
> Preset them with `TM_FR` / `TM_SLOT` (`1`/`0`) to skip the prompts.

You can also double-click `开一局.bat`.

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
| Very low (极低) | 0.24% | ~1.3 |
| Low (低) | 0.60% | ~3.2 |
| Medium (中) | 1.50% | ~8.1 |
| High (高) | 3.75% | ~20 |
| Very high (极高) | 9.38% | ~51 |

Gaps run 2%–12%, direction random. A resting stop can be skipped outright — placing a stop at 126.5
and filling at 131 is common.

### Liquidity · slippage cost

| Tier | 20M notional round trip | 10M position round trip |
|---|---:|---:|
| Ample (充裕) | 3.5% | 1.8% |
| Normal (正常) | 7.0% | 3.5% |
| Thin (纤薄) | 14.0% | 7.0% |
| Drained (枯竭) | 28% | 14.0% |
| Black hole (黑洞) | 56% | 28.0% |

Slippage scales with notional size.

Difficulty is shown in the window title:

```
Tokens Trading Market | your name (ideal conditions) | Black Swan: low | Liquidity: thin
```

---

## Global switches: Preferred Financing and Slot Machine

These are **not** random events. They are global switches chosen at the start, effective for the
whole match, and they can be toggled mid-match.

- Enabling at start: **free**
- Enabling mid-match: **costs 300,000 cash** (disabling is always free)

### Preferred Financing

When enabled:

- **Unlimited** loans per match (still bounded by the 3,000,000 pool and the remaining borrowing limit); the only concession is the target-uplift floor dropping from +1% to +0.01%
- Target-uplift range: `+1% ~ +100%` becomes `+0.01% ~ +100%` (**it always goes up, never reduces the target**; minimum 0.01%)
- The uplift grows with cumulative borrowing: first 300k is about 4%-8%, a full 3M in one go is about 35%-66%
- Splitting a loan into ten parts costs exactly the same as borrowing it all at once

Example: target 2M, borrow 300k and draw +6% → new target = 2M + 18k = **2.018M**

When disabled: unlimited loans, uplift always `+1% ~ +100%`.

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

Calling either after its uses run out returns `次数已用完，拒绝执行` (uses exhausted, refused).

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
| 最小化 (Minimize) | Hides the window; the match keeps running |
| 结束相关进程 (End processes) | Stops the server and closes the window — **counts as one abnormal exit** |
| 结束并结算 (Settle) | Ends the match normally and generates the report |

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
| Risk review (风控审查) | 5 minutes | Borrowing | The 60-second self-rescue window while cash is negative still works |
| Exchange maintenance (交易所维护) | 5 seconds (1 tick) | Closing positions yourself | Blow-up liquidation and end-of-match settlement still work |
| Slot maintenance (老虎机维护) | 8 minutes | Slot bets | — |

All three fire at random. The system will not skip them because you happen to be mid-action.

---

This program is for entertainment and learning only. Nothing here is investment advice.
