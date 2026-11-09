# Cost Model

Every number here comes from actual constants in `tm_engine.py` and real open/close measurements,
not from estimates.

## Four layers of cost

| Layer | Where | How it is charged |
|---|---|---|
| **Commission** | `FEE_RATE = 0.00020` | notional × 0.02%, charged on both open and close |
| **Spread** | `PAIRS[pair]["spread"]` | per pair: AURA 0.06% / FROST 0.08% / AMBER 0.10% / TIDE 0.10% / LUMEN 0.07% / NEON 0.075% / ASH 0.11% |
| **Slippage** | `SLIP_K = 0.00240` | `cost = K / (2 × LIQ) × (after² − before²)`, **quadratic in notional size** |
| **Overnight interest** | `PAIRS[pair]["swap"]` | charged per tick while holding: AURA 0.002% / FROST 0.003% / AMBER 0.004% / TIDE 0.003% / LUMEN 0.002% / NEON 0.0025% / ASH 0.0045% |

## Measured round-trip cost

At "liquidity: thin" (LIQ = 8,000,000, also the default before difficulty is locked), opening and closing immediately (price unchanged, pure
cost):

| Notional | Round-trip cost | As share of 1M starting capital |
|---:|---:|---:|
| 1M | 1,300 | 0.13% |
| 3M | 5,700 | 0.57% |
| 5M | 12,500 | 1.25% |
| 10M | 40,000 | 4.00% |
| 20M | 140,000 | 14.00% |

**The key property**: cost *rate* grows linearly with notional size. Because the slippage term is
`cost ∝ X²`, dividing by notional `X` leaves `cost/X ∝ X`.

## How liquidity tiers change the cost

Same 10M notional, different liquidity tiers:

| Tier | LIQ | Round-trip cost | % of 1M principal |
|---|---:|---:|---:|
| Ample | 32,000,000 | 17,500 | 1.75% |
| Normal | 16,000,000 | 25,000 | 2.50% |
| Thin | 8,000,000 | 40,000 | 4.00% |
| Drained | 4,000,000 | 70,000 | 7.00% |
| Black hole | 2,000,000 | 130,000 | 13.0% |

**So "bad liquidity" does not forbid trading — it forces you to size down.**

## How much price movement you need

Goal: 1M → 2M, i.e. 1M of net profit.

| Notional | Required price move | Including cost | Realistic? |
|---:|---:|---:|---|
| 5M | 20.0% | 21.3% | Barely (a single pair moves 15%–25% in 45 minutes) |
| **10M** | **10.0%** | **14.0%** | Yes — the sweet spot |
| 20M | 5.0% | 19.0% | Cost eats too much |

**10M notional is the theoretical optimum.**

Even then you still need: the direction right (50/50) + capturing the full move + surviving the
drawdown in between.

## Why gaps are the most dangerous thing here

`GAP_CHANCE` base is 1.5% per tick per pair, gap size 2%–12%, **both direction and size random**.

Measured over a 414-tick sample:

- price change on the tick after a gap: `+0.33 / -0.36 / -0.29 / -0.39 / +0.19 / -0.07`
  (mean −0.10%)
- **it neither reverts nor continues** — fitting AR(1) on a series containing gaps yields
  beta = −0.385, which is **spurious regression**

**Gaps cannot be predicted, only absorbed.**

And **stops get skipped**:

```
stop placed at 126.5 → filled at 131.64 (4% slippage)
stop placed at 137   → filled at 139.28 (1.7% slippage)
```

Closing during drained liquidity also incurs about 2.3% slippage (`80.02 → 78.19`).

## Forced liquidation and settlement

A regular close, a blow-up liquidation and end-of-match settlement share **one** execution path:

```
fill = mid price minus/plus (half spread + slippage)
fee  = filled notional x fee rate
```

- **Blow-up liquidation** (margin level = equity / (notional exposure x 10%), below the stop-out line,
  or a margin call timing out):
  spread, slippage and fees all apply, and the fill is written to the trade log with a `forced`
  flag. The report lists "Forced liquidation" under "Closed positions".
- **End-of-match settlement**: not blocked by "exchange maintenance" or any other trading halt.
  Final equity is computed only after positions are cleared:
  final equity = cash - debt, with **no floating P&L**.
- **Failed settlement**: `POST /quit` returns `settled=false` plus `warnings`, and the report
  header reads "Settlement error (N position(s) left open)". It is never treated as a clean result.

> Before v1.0.12 the blow-up path charged fees only (no spread, no slippage), and settlement
> closes were silently skipped while "exchange maintenance" was active. Historical reports use a
> different cost basis and are not directly comparable with v1.0.12 and later.

## How overnight interest accumulates

`LOAN_RATE_PER_TICK = 0.0001` (loan interest), while `swap` is charged on holdings.

One 45-minute match is 540 ticks. Holding 7M notional the whole time:

```
7M × 0.003% (average swap) × 540 ticks ≈ 113,400
```

**That is 11.3% of starting capital** — interest alone can eat a match.

Measured in a real match:

| Item | Amount |
|---|---:|
| Commission | 17,096 |
| Overnight interest | 59,379 |
| **Total** | **76,475** |

In the match that lost 32.38%, **commission plus interest accounted for 23.6% of the total loss**.

More than a fifth of the loss was not bad trading — it was the **cost of staying in**.

## Conclusion

**This game is mathematically negative-sum.**

- Betting at random: negative expectation, win rate 3%–5%
- Disciplined execution (small size, few trades, only extreme deviations): win rate 10%–15%

That is exactly why it is a good test for AI — **it gives no advantage to fast arithmetic, and only
rewards discipline.**
