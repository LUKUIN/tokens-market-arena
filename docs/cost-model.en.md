# Cost Model

> [中文](cost-model.md) · **English**

These are baseline costs for the source edition. Match events can change fees, spread, margin, liquidity and holding costs. The examples below are calculations with fixed inputs.

## Four layers of cost

| Cost | Basis |
|---|---|
| Commission | 0.02% of execution notional per fill, on opening and closing. |
| Spread | Half the effective spread per fill. Base spreads are AURA 0.060%, FROST 0.080%, AMBER 0.100%, TIDE 0.100%, LUMEN 0.070%, NEON 0.075% and ASH 0.110%. |
| Slippage | Before caps and event adjustments, `K / (2 × L) × (after² − before²)`, where `K = 0.0024`. For each fill, exposure is the account's gross notional and `L` is the traded pair's current depth. A close traverses the exposure interval from the remaining amount to the pre-fill amount. |
| Position carry | Applied on the cost clock to the current notional. Rates are AURA 0.0020%, FROST 0.0030%, AMBER 0.0040%, TIDE 0.0030%, LUMEN 0.0020%, NEON 0.0025% and ASH 0.0045% per charge. |

Slippage is capped at 1.4% per fill in ordinary conditions and 6% during a depth shock. The last 15 minutes on the cost clock ramp `K` from 1.0× to 1.5×. Splitting a fill over the same exposure interval gives the same uncapped slippage only when price, depth and modifiers stay fixed.

## Illustrative round-trip costs

Assume an AURA trade starts from zero holdings, is closed immediately at the same mid price, and faces 0.06% spread, base fees, and fixed depth. The rounded estimate excludes carry and the small fee adjustment from using the actual execution price.

| Gross notional | Depth 8M | Cost / starting capital 1M |
|---:|---:|---:|
| 1M | 1,300 | 0.13% |
| 3M | 5,700 | 0.57% |
| 5M | 12,500 | 1.25% |
| 10M | 40,000 | 4.00% |
| 20M | 140,000 | 14.00% |

At 10M gross notional, the same estimate is 17,500 at 32M depth, 25,000 at 16M, 70,000 at 4M and 130,000 at 2M. This isolates the effect of depth.

**The large rows are arithmetic examples.** The baseline opening check requires equity less the new commission to cover 150% of maintenance margin. At the 10% base rate and 1M starting equity, that puts the initial ceiling slightly below 6.67M gross exposure, with the separate occupied-margin check and active events also in force.

At 5M notional, a fixed 12,500 cost raises the break-even move for earning 1M from 20.0% to about 20.25%. This is a simplified illustration. A large price move also changes closing notional and closing costs.

## Gaps and forced liquidation

Base Black Swan gaps are 2%–12% up or down, on top of normal price movement. A gap may pass a planned exit price. The current API offers immediate orders at the current simulated fill and has no resting stop order. A gap triples the affected pair's spread on that step. A depth shock is a separate event that reduces depth and changes the slippage cap.

Maintenance margin is gross exposure × 10% × the current margin multiplier. A level below 100% starts a margin call. Recovery to 100% clears it, otherwise 30 market steps in the call can cause liquidation. Below 50%, liquidation is immediate. Standard closes, margin liquidation and final settlement use the same fill and fee calculations. Automatic settlement bypasses ordinary restrictions on closing and repays the outstanding loan from cash. Settlement warnings can cover residual positions, debt or ledger checks.

## Position carry and loan interest

Carry applies to positions. Loan interest is separate and compounds on outstanding debt at 0.01% per charge. At 540 cost steps, 1M of unchanged principal becomes roughly 1,055,482. At 5M notional and 0.003% carry for 540 charges, the illustrative carry cost is 81,000.

The cost clock counts elapsed match time in 5-second units, bounded by actual market steps. It covers carry, loan interest and the late slippage schedule. The default faster market cadence after a target hit adds price steps rather than multiplying costs by four.

Use the cost attribution in the match report to explain the observed result. The sample reports use different market paths and some use earlier rules. Those samples provide neither an optimal position size nor a model win-rate estimate.
