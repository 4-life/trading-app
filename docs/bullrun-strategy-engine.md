# Bull Run Catch Strategy

A [strategy executor](strategy-executor.md) — trend following with an asymmetric risk/reward: **buys the pullback in an uptrend** (on the paper's timeframe and the next higher one) with a cheap stop under the pullback, moves the stop to **break-even at +1R**, then **trails it 3 × ATR** under the highest high. No take-profit: the trend is held as long as it lasts. **Shorts** mirror it in a downtrend: the rally up to EMA 20 is sold, so a bear market trades too.

Docker service: `bullrun-executor` (`python -m app.executors.bullrun`), executor name `bullrun`. Directions: long / short / both. Meant for **4h** (or 1h) papers (leverage set on the paper) on BTC, ETH, BNB, SOL, HYPE, SOXL, ENA. Target: **over 40% winners** — break-even exits count as wins (they close slightly in profit).

## Signals

The paper's timeframe, closed candles only (the last 1000) — EMA 20 / 50 / 200 of the closes and the 14-candle ATR (Wilder).

| Event | Flat | Position open |
|---|---|---|
| a candle closes a [pullback](#entry) in an [uptrend](#entry) | open **long** | — |
| a candle closes a [rally](#short) in a [downtrend](#short) | open **short** | — |
| price through the [stop](#stop) | — | close (stop-loss / break-even / trailing stop) |

One position at a time; the paper's `direction` limits the entries.

### Entry

- **Uptrend** — the close above EMA 200, and EMA 50 above EMA 200.
- **Higher-timeframe uptrend** — the last closed candle of the next higher timeframe (**1h → 4h**, **4h → 1d**; UTC boundaries) closes above its **EMA 50**, and that EMA is rising. Built from the paper's own candles: a candle ending on a higher-timeframe boundary closes that candle with its close. Other timeframes skip this filter.
- **Pullback** — a low at or under EMA 20 in the signal candle or the 5 before it.
- **Signal candle** — closes above EMA 20 **and** above the previous candle's high: the dip is over.
- One entry per signal candle — after a stop, the next long needs a new signal.

### Short

The long's rules on the prices upside down — highs and lows swapped (in code: a short is a long on the negated prices, so the rules exist once):

- **Downtrend** — the close below EMA 200, EMA 50 below EMA 200, and the higher timeframe's last closed candle below its **falling** EMA 50.
- **Rally** — a high at or above EMA 20 in the signal candle or the 5 before it; the signal candle closes below EMA 20 **and** below the previous candle's low.
- **Stop** — above the rally's highest high, 0.5–1 × ATR above the entry; break-even at entry − 1R (stop **entry − 0.2%**); then **3 × ATR above the lowest low since entry**.

### Stop

| Stage | Stop | Exit reason |
|---|---|---|
| from entry | under the pullback's lowest low, kept **0.5–1 × ATR** under the entry (long; [short](#short) mirrored) | `stop_loss` |
| a candle's high reached **entry + 1R** (R: entry − initial stop) | **entry + 0.2%** (fees and slippage) | `break_even` |
| **highest high since entry − 3 × ATR** is above that | follows it | `trailing_stop` |

- The initial stop is recorded on the entry. The break-even and trailing stop come from the candles closed since entry and the current ATR.
- Checked every executor pass (5 s) against the **latest trade price** (the last closed candle's close if no trade arrived in the last 60 s).

## Decision Log Reasons

| Reason | |
|---|---|
| `pullback_entry` | a pullback closed in an uptrend (long) / a rally in a downtrend (short) |
| `stop_loss` | the initial stop |
| `break_even` | the break-even stop |
| `trailing_stop` | the 3 × ATR trailing stop |

## Backtest

**Temporary**, like the [VWAP backtest](vwap-strategy-engine.md#backtest) — same `backtest_trades` table, chart and statistics; run when a paper is [prepared](papers.md#preparation), or by hand after a backfill:

```bash
docker compose -f docker/local/compose.yaml exec bullrun-executor python -m app.backtest.bullrun [YYYY-MM-DD]
```

- Candle-level approximation of the live executor: a signal candle opens the long at its close.
- Each candle's stop comes from the candles closed before it; a candle trading at or under it closes the long at the stop — at the open if it opened under it — and fills **0.05% further** (the live executor checks every 5 s and closes at market). The same candle may open the next long at its close.
- `return_pct` — net of both maker fees of the selected provider, as for VWAP; a position still open on the last candle isn't stored.

---
[← Back to README](../README.md)
