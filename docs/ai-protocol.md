# Agent Integration Protocol

The HTTP API is for a 45-minute simulation. Commands below use the default address `127.0.0.1:8734`. Use the actual `TM_PORT` if it differs. Start with [AGENTS.md](../AGENTS.md), then keep [game rules](rules.md) and [the cost model](cost-model.md) handy.

## Start and lock the difficulty

1. Run the project from its root on Python 3.14. The regular launcher opens a spectator. Use `--headless` for a session without a desktop.
2. Wait for `GET /health` to return `ok:true`. This means HTTP is ready. The market may still be waiting for a challenge answer or a difficulty lock.
3. For a fresh match, read `GET /state`. If `challenge.stage` is `ask`, call `POST /challenge/accept` or `POST /challenge/decline`. After 75 seconds with no answer, the engine declines. The challenge and difficulty wait do not use the 45-minute trading clock.
4. The 30-second difficulty countdown starts automatically after the answer. Wait for it or call `POST /roll/stop` to lock immediately. Confirm `rolled:true` in `GET /state`. If you enabled challenges, their three objectives appear at the lock.

For example, in a fresh session in Bash or with `curl.exe` on Windows, decline first, then lock.

```bash
curl -X POST http://127.0.0.1:8734/challenge/decline
curl -X POST http://127.0.0.1:8734/roll/stop
curl http://127.0.0.1:8734/state
```

Use `TM_TRADER` before startup to set the contestant name. This also avoids the unnamed-session disqualification. For leftovers from an interrupted match, follow the Windows cleanup steps in [AGENTS.md](../AGENTS.md) after closing that checkout's process.

## GET endpoints

| Endpoint | Response |
|---|---|
| `/health` | `ok`, `tick`, `equity`, `finished`, `protocol` and `engine_version`. |
| `/state` | State object. With `?history=0`, `price_history` is `{}`. Equity history and recent events still appear. |
| `/prices` | Map from symbol to `{price, name, spread_pct}`. History is in `/state`. |
| `/rules` | In-game rule summary, including effects for 40 random events and three tiers of criteria for 20 challenge objectives. Refer to this page for assistance, pause and quote-history behavior. |
| `/roll/state` | `{ok, roll_left, rolled}`. While the challenge answer is pending, the roll timer does not count down. |
| `/special` | Feature settings and counters. `fr_left` is always `null`. `slot_left` is `null` if disabled. |
| `/scratchpad` | `{ok, items}` or `{ok, count}` with `?count=1`. |
| `/assist/pending` | Spectator-side requests and recent conversation. |
| `/assist/inbox` | Unread spectator replies in `items`. Fetching marks them as read. |

## POST endpoints

Use a UTF-8 JSON object for bodies. Example bodies appear below. Check `ok` on actions even with HTTP 200. Some read endpoints return a bare object without an `ok` field. Expect transport failures separately from game rejections.

| Endpoint | Body and behavior |
|---|---|
| `/open` | `{"pair":"AURA/CORE","side":"LONG","lots":1,"leverage":20}`. All four fields are required. |
| `/close` | `{"pair":"AURA/CORE","side":"LONG","lots":1}`. Omit `lots` or pass zero to close all matching positions. Omit `side` to include both directions. A partial close without `side` starts at the newest matching position. |
| `/close_all` | No body. Attempts every open position using normal close rules and can fail during a close restriction. Check the resulting state. |
| `/loan` | `{"amount":100000}`. Subject to the remaining pool and current restrictions. Returns the target increase for this loan. |
| `/repay` | `{"amount":50000}`, or omit `amount` to request full repayment. The payment is limited by debt and available cash. |
| `/slot` | `{"amount":10000}`. If enabled, at most three plays, each 1–200,000 Tokens and capped by cash balance. |
| `/special` | `{"name":"fr","on":true}` or `{"name":"slot","on":false}`. Turning a feature on requires a pre-start session. Turning it off is allowed during play. Use a JSON boolean for `on`. |
| `/challenge/accept`, `/challenge/decline` | No body. Answer while `challenge.stage` is `ask`. |
| `/roll/start`, `/roll/stop` | No body. The normal flow starts the draw automatically after the challenge answer. `/roll/stop` locks it. |
| `/fastforward` | `{"seconds":300}` or `{"seconds":180}`. See the budget and cooldown below. |
| `/scratchpad` | `{"text":"..."}` appends a note. `{"clear":true}` clears the notes. |
| `/assist/ask` | `{"text":"..."}`. Returns a `ticket`. Up to three requests per match when assistance is enabled. |
| `/assist/reply`, `/assist/reject` | Spectator-side response. Send `ticket` and, for a reply, `text`. |
| `/assist/enable` | Retained for compatibility and always fails. Set `TM_ASSIST=1` before startup to enable assistance, or `0` to disable it. |
| `/trader` | `{"name":"Model-Effort-Platform"}`. Changes the display name. Set `TM_TRADER` at startup for eligibility. |
| `/pause`, `/begin` | Pre-start controls. `/pause` does not toggle or pause an already started match. No call is needed in the standard flow. |
| `/reset` | No body. Replaces the match while the service is running, preserves reports and has a 30-second cooldown. A reset clears audience assistance; restart the service to apply `TM_ASSIST` again. |
| `/quit` | No body. Check the settlement conditions below before calling it. |
| `/shutdown` | Administrative stop. The service attempts to write an abnormal-exit snapshot without settlement. |

## Reading state

| Field | Meaning |
|---|---|
| `session_id`, `tick`, `elapsed_seconds` | Match ID, number of market steps, and elapsed match seconds. One market step normally takes 5 seconds; fast-forward and the post-target cadence affect how these values advance. |
| `equity`, `balance`, `genesis`, `target` | Equity is cash plus unrealized P&L minus debt. Cash is the slot spend limit. `genesis` is the P&L baseline. Use `target` for the current goal. |
| `rolled`, `difficulty`, `challenge` | Difficulty indices `gap` and `liq` are 0–4. `difficulty` is `null` before locking. Tasks are empty until an enabled challenge is drawn. Result tasks show live `progress`. Double or Nothing uses `key: double_goal`. |
| `prices`, `liquidity`, `active_mods` | Current mid prices with base spreads, per-symbol liquidity relative to the selected tier, and active modifiers. `liquidity` is a multiplier, not the depth in Tokens. |
| `positions`, `margin_used`, `maint_margin`, `maint_rate`, `margin_level` | Position rows, occupied margin, and the maintenance amount, base rate and current coverage. `margin_level` is a percentage or `null` with no open position. |
| `loan`, `loan_bump_range`, `special` | Loan balance, limit, interest and target increases. `loan_bump_range` reports the standard financing setting. Double or Nothing uses 50–100% for each loan and slot payout. `special.slot_win_range` reflects that challenge. |
| `ff`, `negative_remain`, `margin_call_remain` | Fast-forward quota and cooldown in seconds, remaining cash-rescue time in seconds, and margin-call grace in market steps. |
| `price_history`, `equity_curve`, `events` | At most 600 prices per symbol, 900 equity points and the latest 60 events. Use `(session, seq)` to deduplicate events. Action responses that include a compact `state` omit these series' contents. |
| `huge_wave` | Pre-warning flag for the current step and counters `total`, `left` and `fired`. |
| `closed_n`, `win_n`, `profit_factor` | Closed-fill count, profitable close count, and gross profits divided by absolute gross losses; `null` if the denominator is zero. |
| `audit`, `settlement`, `finished`, `disqualified` | Audit messages, latest settlement result, completion flag and eligibility indicator. An empty audit means those checks found no issues. |
| `seed`, `assist_unread` | Seed is available after settlement. The unread count directs you to `/assist/inbox` for message contents. |

## Fast-forward

The total budget is 900 seconds. A 300-second advance starts a 120-second real-time cooldown. A 180-second advance starts a 90-second cooldown. Send options only when the corresponding `ff.can5` or `ff.can3` is true. A full 300-second request normally advances 60 steps. If the match ends during the request, inspect the returned `ticks`, `seconds` and `state.finished` before acting again. Market ticks continue automatically during cooldown.

## Settlement and reports

Read `/state` before `/quit`. At or above the current target, close open positions first and read the updated equity. If closing costs push equity below target, quitting counts as abandonment. Below target, quitting settles remaining positions and debt. Eligibility also matters to a recorded target hit.

**v1.2.28 schedules a server shutdown about three seconds after a `/quit` request even when `ok:false`. Treat `/quit` as terminal, and use state polling for the preflight.** When time expires, the engine applies regular close costs in automatic settlement. `hit_at_tick` records the first observed target hit, and the final result can still be a miss.

A successful response contains `final_equity`, `report`, `settled` and `warnings`. Reports are under `src/data/reports/HTML Reports/` and `src/data/reports/JSON Reports/`. A false `settled` flag calls for checking `warnings`. Wait for a normal shutdown to finish before starting a new service from the same directory.

## Notes and fair play

During a match use the scratchpad HTTP endpoints. The packaged `src/scratchpad.py` is one of the files sealed by the guard, and executing a decoy can terminate the match. Only notes submitted to the scratchpad are included there in the report. Spectator replies arrive via `/assist/inbox`, separate from the event stream.

Use API data and your own analysis during a competition. Run integrations as a single writer when the order matters. Serialization of engine operations does not make a repeated POST safe to retry after a timeout, so read back the state before resending a trade.
