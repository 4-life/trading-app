# Trend Strategy

A [strategy executor](strategy-executor.md) that catches big moves — a bull run or a panic sell — on a breakout and rides them with a volatility trailing stop, under a hard **1% stop-loss**.

Docker service: `trend-executor` (`python -m app.executors.trend`), executor name `trend`. Directions: long / short / both. Meant for **4h** papers on **many assets** (it's right ~40% of the time; the profit comes from a few big trends, so it needs many markets) — best run as a [scanner paper](papers.md#scanner-papers), which finds the breaking-out coins among the top 40 itself.

## Signals

Closed candles of the paper's timeframe only — except the stop-loss, which reads closed **1m** candles.

| Event | Flat | Position open |
|---|---|---|
| a candle closes **above the highest high of the previous 20 days**, [confirmed](#breakout-confirmation) | open **long** | — |
| a candle closes **below the lowest low of the previous 20 days**, [confirmed](#breakout-confirmation), while the market is in a [bear phase](#bear-market-filter) | open **short** | — |
| a **1m** candle closes **1%** against the entry (below it for a long, above it for a short) | — | close (**stop-loss**) |
| a candle closes **3 × ATR** beyond the best price since entry (below the highest high for a long, above the lowest low for a short) | — | close (**trailing stop**) |

- **ATR** — average true range over 14 candles (Wilder smoothing): the typical candle size, so the stop is wider for volatile assets and narrower for calm ones.
- **The stop only moves in the trade's favour** — it follows the best price since entry, never back.
- **Stop-loss** — 1% from the entry price, whatever the paper's timeframe: every executor pass (5 s) compares the latest closed 1m candle's close with it, so a loss is cut within about a minute instead of at the paper's candle close. The trailing stop takes over once it's above the entry (long) / below it (short).
- The stop recorded on the entry is the nearer of the two (usually the 1% one).
- No take-profit: a trend is held as long as it lasts.
- The paper's `direction` limits the entries; shorts also need the bear filter.

## Breakout Confirmation

A close beyond the 20-day range alone is weak evidence — many such breakouts fail at once. The breakout candle must also show:

- **Volume** — at least **2×** the average volume of the previous 20 candles: real buying (selling) behind the move.
- **Strong close** — in the **top quarter** of the candle's range for a long (bottom quarter for a short): no big wick against the breakout, i.e. the price wasn't already pushed back by the close.

The [scanner](papers.md#scanner-papers) uses the same rule, so it only picks confirmed breakouts.

## Bear-Market Filter

Shorts open only while **BTC closes below its 200-day average**, at the paper's timeframe. In the backtest, shorts lost money on their own (crashes bounce hard and stop them out) but paid off in a falling market — the filter keeps them for that phase only.

- Read from BTC candles: the [backfill](market-data.md#historical-backfill) adds BTC at every trend paper's timeframe, and `BACKFILL_DAYS` (default 220) covers the 200 days.
- Not enough BTC history → no shorts (longs are unaffected).

## Why These Settings

The settings are the textbook ones (20-day breakout, 3 × ATR, 200-day filter), **not tuned**: in the hold-out test, settings picked as the best on one half of the history lost on the other half, while these worked in both.

Backtest (4h, the 19 most traded coins of mid-2024 including later delisted ones, June 2024 – October 2026, equal capital per coin, fees + slippage + funding):

| | Per year | Worst drop | Jun 2024 – Aug 2025 | Aug 2025 – Oct 2026 |
|---|---|---|---|---|
| Buy & hold the same coins | −20% | −78% | +8% | −47% |
| Trend, long only | +16% | −13% | +30% | +11% |
| Trend, long + shorts in a bear phase | +19% | −19% | +22% | +25% |

Expect long flat or losing stretches between big trends. The backtest predates the 1% stop-loss and the breakout confirmation.

## Decision Log Reasons

| Reason | |
|---|---|
| `breakout_high` | long entry |
| `breakout_low` | short entry |
| `stop_loss_1pct` | the 1% stop-loss (1m close) closed the position |
| `trailing_stop` | the trailing stop closed the position |

---
[← Back to README](../README.md)
