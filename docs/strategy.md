# Phase-1 edge hypothesis (one page)

**Strategy:** short-horizon **momentum** on 1-minute CoinDCX candles, with a **volume confirmation** filter. Long-only by default (CoinDCX spot cannot short without futures + API keys).

## Why this, not mean-reversion

On liquid USDT pairs, a 10–20 minute burst with rising volume is more often **order-flow continuation** than a finished mean-revert snap — at least that is the hypothesis to *test* in paper. Mean-reversion is a reasonable alternative, but Phase-1 implements **one** rule so the ledger is interpretable.

We are not claiming a proven edge. CoinDCX taker fees (~20 bps + GST) plus 1 bp paper slippage mean a **round trip costs ~47 bps**. The signal must therefore be rare and relatively large, or it will bleed to fees.

## Exact rule (code: `paperbot/strategy/momentum.py`)

On each loop, for each whitelist market:

1. Fetch 1m candles (`GET /market_data/candles?pair=B-BTC_USDT&interval=1m`). Drop the newest bar so we only decide on **closed** candles.
2. `ret` = close / close[lookback] − 1. Default `MOM_LOOKBACK=15` (~15 minutes).
3. `vol_ratio` = mean(volume of last 3 bars) / mean(volume of the 15 bars before that). Require `vol_ratio >= MOM_VOLUME_MULT` (1.2).
4. **Enter long** if `ret >= MOM_ENTRY_RET` (0.25%) and volume confirms, we have no position in that market, open-position cap allows it, and Kelly size > exchange min notional.
5. **Exit** on first of: stop `−MOM_STOP_PCT` (0.40%), take `+MOM_TAKE_PCT` (0.60%), momentum fade (`ret <= MOM_EXIT_RET`), or `MOM_MAX_HOLD_BARS` (12 minutes).

Paper fill price = last trade ± `SLIPPAGE_BPS`. Fee = notional × `FEE_BPS` × (1 + `FEE_GST_PCT`/100) on both entry and exit.

## Sizing

Until 10 closed paper trades exist, Kelly uses the prior `p=0.52`, `b=1.15` (payoff ratio). That full Kelly is ~10%; **half-Kelly ~5.1%**, then the **6% hard cap**. After 10 exits, p and b are Laplace-smoothed from the ledger. Negative edge → size 0.

## What “good” looks like after 1–2 weeks

Run continuously on live CoinDCX (`python -m paperbot run`). Inspect daily with `status` / `pnl`.

| Check | Healthy paper result | Bad / stop |
| --- | --- | --- |
| Trade count | Tens of closed trades, not hundreds/day | Firing every bar → thresholds too loose |
| After-fee expectancy | Mean closed PnL ≥ 0, or only slightly negative while you tune | Steady bleed ≈ 2× fee every trade |
| Win rate × payoff | Win rate ≥ 45% with avg win / avg loss ≥ 1.1, **or** lower win rate with clearly larger winners | ~50% wins of the same size as losses (fees dominate) |
| Drawdown | IST daily loss rarely near 3% breaker; equity DD from start < ~8% | Breaker trips more than once a week |
| Turnover vs fees | Fees remain a minority of gross | Fees ≈ |realized| |
| Sanity vs BTC/ETH | Bot is not just secretly long BTC in a raging bull (compare to buy-and-hold of the same pairs) | Equity only up when BTC is up 1:1 |

If after two weeks expectancy is negative after fees, **do not** arm live trading. Tighten `MOM_ENTRY_RET`, raise `MOM_VOLUME_MULT`, or abandon this hypothesis. The ledger is the proof, not the narrative.

## What this will not do

- No funding-rate filter (spot).
- No shorts unless you set `ALLOW_SHORTS=true` (still paper; live spot still cannot short).
- No Polymarket, Twitter, or other venues.
- No claim that 15-minute crypto momentum “works.” Phase-1 exists to measure whether it *might* after CoinDCX costs.
