# Game Rules

> Derived from the packaged AI edition rules. Parameters are identical to the Human edition; only
> the way you operate differs.

## Starting up

Start from the repository root with Python 3.14. See [AGENTS.md](../AGENTS.md) for launcher commands. `python run.py` reads environment settings and opens the spectator. The interactive demo has its own console prompts. In a fresh HTTP session, answer the challenge prompt first (75 seconds, default decline), then wait for the 30-second draw or lock it early. The 45-minute trading clock starts at the lock.

`TM_TRADER` records the contestant. Check `rolled:true` before trading. When an idle limit is configured, the engine measures successful state-changing actions in market steps. The normal script entry defaults to zero (disabled). The double-click launcher defaults to 12 minutes. See [the integration protocol](ai-protocol.md) for examples.

## Difficulty

Difficulty has two dimensions, drawn at the start, five tiers each. They govern two different
things:

- **Black Swan** — how often risk hits
- **Liquidity** — how large a position you dare to hold

### Black Swan · gap probability per pair per tick

| Tier | Chance | Expected per pair in 540 baseline steps |
|---|---:|---:|
| Very low | 0.24% | About 1.3 |
| Low | 0.60% | About 3.2 |
| Medium | 1.50% | About 8.1 |
| High | 3.75% | About 20 |
| Very high | 9.38% | About 51 |

Base gaps are 2%–12% up or down and may pass the planned exit price. The API has no resting stop orders.

### Liquidity · slippage cost

Base depths are 32M, 16M, 8M, 4M and 2M Tokens from Ample to Black Hole. Depth varies by symbol during play. See the [cost model](cost-model.md) for slippage and the opening limits.

## Global switches: Preferred Financing and Slot Machine

These are **not** random events. They are global switches chosen at the start, effective for the
whole match. They can only be decided at the start.

- Enabling at start: **free**
- **Once the match begins they can no longer be turned on** (turning one off is always free)

### Preferred Financing

The standard target-uplift range is +1% to +100%. Preferred Financing lowers the floor to +0.01%. Both modes allow repeated loans subject to the remaining pool, normally 3M minus outstanding debt. The base ratio uses average cumulative pool utilization across the new loan, and each loan has a separate random factor. The realized uplift can change when the same total is split across loans.

For example, a 300k loan at a realized +6% adds 18k to the target. Repaying reduces outstanding debt and interest charges. Loan interest compounds at 0.01% per cost step. See the [cost model](cost-model.md).

### Slot Machine

When enabled:

- **3 plays** per match, `1 – 200,000` per play, capped by your cash balance
- **80%** nothing / **15%** refund 5× / **5%** refund 10×
- Winnings go to cash; each payout also adjusts the target by −5% to +100% of that payout

### Combined target formula

`target = base goal + sum(each loan × its draw) + sum(each slot payout × its draw)`. Double or Nothing doubles the target at the draw and uses a 50–100% uplift for later loans and payouts. The caps and odds still apply.

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
- The market continues to advance on its own during cooldown.

### What the spectator window can do

The AI edition's spectator is **read-only**: no order buttons, no fast-forward button, and no "settle" button. The window also provides an administrative stop and minimization.

| Action | Effect |
|---|---|
| Minimize | Hides the window; the match keeps running |
| End processes | Stops the server and closes the window — **counts as one abnormal exit** |

End a match normally with `POST /quit` (settles and writes the report); do not use "End processes" for that.
At or above target, close all positions and check the resulting equity first. v1.2.28 schedules shutdown even if `/quit` rejects the request.

---

## FAQ

- If a challenge is pending, answer it first. The difficulty countdown begins afterwards.
- If the spectator is missing, check the terminal and the desktop requirements in the [README](../README.md). An occupied port or a missing WPF runtime can prevent the expected window from opening.
- Reports are under `src/data/reports/HTML Reports/` and `src/data/reports/JSON Reports/`. The report seed, difficulty index, engine version and event settings are needed to reproduce the market path.
- Use `/reset` only while the service is running. Once the service exits, start a new process.

## Challenge tasks (a port of PvZ2 Level Objectives)

A fresh match starts with a prompt to enable challenges. Answer with `POST /challenge/accept` or `POST /challenge/decline`. After 75 seconds without an answer, the engine declines and starts the difficulty draw.

If enabled, the engine draws **one result objective and two process objectives** from 20 candidates when difficulty locks. Process violations are recorded immediately. Trading milestones can clear during play, and equity targets are judged at settlement.

### Objective pool

| Objective | How it is judged | Tiers (low / medium / high difficulty) |
|---|---|---|
| No Borrowing | Never borrow from the loan pool | — |
| No Blow-up | Avoid margin liquidation during play | — |
| Self-reliant | Never use the Crowd's Mercy | — |
| No Locked Pairs | Never hold long and short on the same pair | — |
| Fee Discipline | Cumulative fees stay under X of capital | 1.5% / 1.0% / 0.7% |
| Drawdown Guard | Max equity drawdown stays under X | 18% / 12% / 8% |
| Light Footprint | At most X position rows, counting long and short separately | 4 / 3 / 2 |
| Margin Cushion | Margin level never drops below X while holding | 150% / 180% / 220% |
| Clear of Margin Calls | Avoid margin calls and margin liquidation | — |
| Low Leverage | Stay within the leverage limit for every open or add | 30x / 20x / 10x |
| Size Discipline | Gross exposure stays within a multiple of starting capital | 3x / 2.5x / 2x |
| Carry Budget | Cumulative holding costs stay within the cap | 2% / 1.4% / 0.9% of starting capital |
| No Slot Bets | Skip all slot bets | — |
| Patience Pays | Voluntarily close each position in full at least 5 ticks after the last open or add | 1 / 2 / 3 positions |
| Beat the Target | Final equity reaches a percentage of the current target | 110% / 120% / 130% |
| Double or Nothing | Final equity meets the live target, which starts doubled at 4 million | Slot payouts and loans raise the target by 50–100% of the amount |
| Small Gains | Close at least one trade voluntarily and finish above starting capital | +3% / +5% / +8% |
| Profit in Hand | Reach a net profit threshold on one voluntary close | 1% / 1.5% / 2% of starting capital |
| Multiple Winners | Reach a cumulative net profit threshold on each of several pairs | 2 at 0.2% / 2 at 0.3% / 3 at 0.5% of starting capital |
| Both Directions | Reach a cumulative net profit threshold on long and short trades separately | 0.3% / 0.5% / 0.8% of starting capital per side |

Drawing rules:

- Double or Nothing has a 1 in 19 chance. Each of the other six result objectives has a 3 in 19 chance.
- The two process objectives come from different categories. Tasks about assistance and slot bets require the corresponding feature to be enabled at the draw.
- Thresholds follow the difficulty tier: `tier = max(black-swan tier, liquidity tier)`,
  0–1 use the loose column, 2 the medium one, and 3–4 the strict one

### Three states

| Mark | Meaning |
|---|---|
| √ | cleared (trading milestones lock immediately, and equity targets are checked at settlement) |
| × | broken (a process objective is failed permanently once violated) |
| · | in progress |

The engine checks objectives after market steps and relevant successful actions. Net profit for Profit in Hand, Multiple Winners and Both Directions uses executed prices and deducts entry and exit fees. Holding costs and loan interest are accounted for separately. Settlement fees count toward Fee Discipline, and the final equity change counts toward Drawdown Guard.

The spectator window's "Challenge Tasks" card shows each objective's name, exact rule,
current state and the reason it broke; the event feed records entries prefixed
`[Challenge]`. When the contestant declines, the card reads
"The contestant did not enable challenge tasks".

Three boundaries:

- **The challenge prompt and difficulty draw are outside the 45 minutes.** The trading clock starts when the difficulty locks.
- **A broken objective never recovers**: once ×, it stays ×
- Double or Nothing changes the target and later loan and payout uplifts.

## Random events and Huge Wave warnings

The pool has 40 random events. `GET /rules` lists their scopes, effects and durations. Market Maker Withdrawals and Depth Recovery apply 0.75x and 1.5x effective depth, respectively, for 10 steps. Depth affects slippage and is reflected in `active_mods` and each pair's `liquidity`.

When random events are enabled, the match draws 0–3 warnings with equal 25% chances. The first warning is eligible from market step 30. In the regular phase, warning starts are spaced by at least 36 steps and each eligible step has a 1% trigger probability. The final three minutes can shorten the spacing and remove the probability gate. An early exit can leave warnings unused.

The warning banner is displayed on step `t`, with a Windows system sound in WPF. Ordinary news pauses while normal price movements and Black Swan gaps continue. The burst on step `t+2` draws 3–5 weighted risk events with distinct mechanisms, including at least one price shock. Each burst can apply at most one market-wide price shock and one change per modifier. Two market steps normally take 10 seconds. Fast-forward or a faster cadence can shorten the real-time warning window.

`huge_wave.total` is the number drawn, `fired` is the number whose warnings started, and `left` is the number yet to start. The warning announces timing without revealing direction or magnitude.

## Platform-restriction events (random)

| Event | Duration | Blocks | Exception |
|---|---|---|---|
| Risk review | 60 steps (about 5 min at normal speed) | Borrowing | The 60-second self-rescue window while cash is negative still works |
| Exchange maintenance | 1 market step | Closing positions yourself | Blow-up liquidation and end-of-match settlement still work |
| Slot maintenance | 96 steps (about 8 min at normal speed) | Slot bets | — |

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
