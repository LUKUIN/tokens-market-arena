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

**The very first thing a round asks** is: **does this round run with challenge tasks?**
Answer with `POST /challenge/accept` or `POST /challenge/decline` within 75 seconds;
no answer means "off". Prices, the round clock and the difficulty roll all wait during that
window, so the answer never costs you time.

After you answer or time out, the engine rolls the difficulty. If enabled, **the moment it is fixed**, three
objectives are drawn with that tier's thresholds and published together with it, staying fixed
for the rest of the round. Judging runs live:
breaking an objective marks it × permanently, meeting one marks it √ immediately.

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
| Patience Pays | Close at least X position(s) held for 5 ticks | 1 / 2 / 3 |
| Beat the Target | Equity reaches X of the target | 120% / 150% / 200% |
| Double or Nothing | Equity reaches the current target (doubled when drawn) | Target x2; slot and loan target bumps fixed at 50%-100% |

Drawing rules:

- **At least one result-type objective** (Patience Pays / Beat the Target / Double or Nothing) is always included:
  three "do not do X" titles would reduce the round to doing nothing
- The three are distinct; Double or Nothing and Beat the Target are mutually exclusive
  (the target is already doubled, stacking 200% would make it 4x and the round a certain loss)
- Thresholds follow the difficulty tier: `tier = max(black-swan tier, liquidity tier)`,
  0–1 use the loose column, 2 the medium one, and 3–4 the strict one

### Three states

| Mark | Meaning |
|---|---|
| √ | cleared (result-type objectives can clear early and then stop changing) |
| × | broken (a process objective is failed permanently once violated) |
| · | in progress |

At settlement the engine resolves pending objectives. A result objective confirmed earlier remains cleared even if equity later falls.

The spectator window's "Challenge Tasks" card shows each objective's name, exact rule,
current state and the reason it broke; the event feed records entries prefixed
`[Challenge]`. When the contestant declines, the card reads
"The contestant did not enable challenge tasks".

Three boundaries:

- **The answering window does not eat the 45 minutes**: the clock is rebased when you answer (or time out)
- **A broken objective never recovers**: once ×, it stays ×
- Double or Nothing changes the target and later loan and payout uplifts.

## Huge Wave warning (a special event)

When random events are enabled, the match draws 0–3 warnings with equal 25% chances. The first warning is eligible from market step 30. In the regular phase, warning starts are spaced by at least 36 steps and each eligible step has a 1% trigger probability. The final three minutes can shorten the spacing and remove the probability gate. An early exit can leave warnings unused.

The warning banner is displayed on step `t`, with a Windows system sound in WPF. Ordinary news is suppressed while the warning is pending; normal price movement and Black Swan gaps can still occur. The burst on step `t+2` applies 3–5 weighted risk events in that step. Two market steps normally take 10 seconds. Fast-forward or a faster market cadence can shorten the real-time warning window.

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
