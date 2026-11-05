# Game Rules

> [中文](rules.md) · **English**

> Derived from the packaged AI edition rules. Parameters are identical to the Human edition;
> only the way you operate differs.

## Starting up

```bash
set TM_TRADER=<model>-<effort>-<agent-platform>
set TM_EVENTS=1
python run.py
```

The server listens on `127.0.0.1:8734`; the GUI is a read-only spectator. Startup order:
player name → random events on/off → **Finance Reversal** switch → **Slot Machine** switch →
server starts → difficulty draw (30 s, lock early with `POST /roll/stop`) → clock starts →
the model trades over HTTP.

> Both global switches are decided after the events question and before the difficulty draw.
> Preset them with `TM_FR` / `TM_SLOT` (`1`/`0`) to skip the prompts.

You can also double-click `启动游戏.bat`.

> This document covers the **AI edition**. The Human edition (`TokensMarket-OpenSource-Human`)
> has an investment panel; its rule parameters are the same as here.

---
  Difficulty has two dimensions, drawn at the start, five tiers each
  They govern two different things:
    Black Swan  = how often risk hits
    Liquidity   = how large a position you dare to hold
---

【Black Swan】gap probability per pair per tick

  Tier       Chance    Expected gaps per pair in 45 min
  ------------------------------------------------------
  极低 (very low)  0.24%   ~1.3
  低 (low)          0.60%   ~3.2
  中 (medium)       1.50%   ~8.1
  高 (high)         3.75%   ~20
  极高 (very high)  9.38%   ~51

  Gaps run 2%–12%, direction random.
  A resting stop can be skipped outright (placing at 126.5 and filling at 131 is common).

【Liquidity】slippage cost

  Tier              20M notional round trip   10M position round trip
  ------------------------------------------------------
  充裕 (ample)       3.5%                       1.8%
  正常 (normal)      7.0%                       3.5%
  纤薄 (thin)       14.0%                       7.0%
  枯竭 (drained)    28%                        14.0%
  黑洞 (black hole) 56%                        28.0%

  Slippage scales with notional size.

  Difficulty is shown in the window title:
    Tokens Trading Market | your name (ideal conditions) | Black Swan: low | Liquidity: thin

---====================================
  【Finance Reversal】and【Slot Machine】global switches
---

These are not random events. They are **global switches** chosen at the start: they apply for the
whole match and can be toggled mid-match.

  Enabling at start: free
  Enabling mid-match: costs 300,000 cash (disabling is free)

【Finance Reversal】when enabled:
  At most 2 loans per match (no per-loan cap, but the borrowing limit still applies)
  Target-uplift range: +1% ~ +100%  →  -20% ~ +100%
  A negative draw means the target is reduced (borrowing can lower your goal)
  Example: target 2M, borrow 3M, draw -20% → new target = 2M - 0.6M = 1.4M

  When disabled: unlimited loans, uplift always +1% ~ +100%

【Slot Machine】when enabled:
  3 plays per match, 1 ~ 200,000 per play, never above your current equity at bet time
  80% nothing / 15% refund 5× / 5% refund 10×
  Winnings go to cash; the target also rises by -5% ~ 100% of the winnings

Combined formula:
  Total = original target
        + total borrowed × U(1%~100%)        ← Finance Reversal off
        + total borrowed × U(-20%~100%)      ← Finance Reversal on
        + total slot winnings × U(-5%~100%)  ← Slot Machine on

  The two increments are drawn independently; if only one switch is on, only that term applies.

Calling either after its uses are exhausted returns "次数已用完，拒绝执行" (uses exhausted, refused).

---====================================
  Fast-forward
---

Each match gets 15 minutes (900 seconds) of fast-forward budget. Two tiers, freely mixed:

  Tier        Each jump   Cooldown after
  ------------------------------------------
  5 minutes   300 s       120 s
  3 minutes   180 s       90 s

  The 30-second difficulty draw does not count against the 45 minutes — the clock starts at lock.
  Cooldown depends on the tier you used.
  During cooldown the buttons are greyed out.
  If the remaining budget cannot cover a tier, that jump does not execute.
  Example: used 5′+3′+3′+3′ = 840 s, 60 s left — neither tier is usable.
  The UI shows remaining budget, the record of jumps, and the cooldown countdown.
  In the AI edition, manual `/tick` shares the same budget and cooldown — it cannot be bypassed.

  The three buttons
---

「最小化」 Minimize      hide the window, the match keeps running
「结束相关进程」 End processes   stop the server and close the window (counts as one abnormal exit)
「结束并结算」 Settle      end the match normally and generate the report

---
  FAQ
---

Q: Double-clicked the bat and it sits at "drawing difficulty"?
A: That is the 30-second countdown. Click "lock" to freeze it early.

Q: The main window never appears?
A: You are still in the difficulty draw or the rules window — check whether another window covers it.

Q: Where is the report?
A: An .html file per match under `src/data/reports/`.

Q: How do I start over?
A: The bottom of the investment panel has "restart match".

Q: Windows warned and blocked the file?
A: The source edition has no .pyd; only the .bat may be blocked by SmartScreen.
   Right-click the bat → Properties → tick "Unblock" → OK. Once is enough.

---
  This program is for entertainment and learning only. Nothing here is investment advice.
---


### Platform-restriction events (random)

| Event | Duration | Blocks | Exception |
|---|---|---|---|
| Risk review | 5 minutes | Borrowing | The 60-second self-rescue window when cash is negative still works |
| Exchange maintenance | 5 seconds (1 tick) | Closing positions yourself | Forced liquidation on insufficient margin still works |
| Slot maintenance | 8 minutes | Slot bets | — |

All three fire at random. The system will not skip them because you happen to be mid-action.
