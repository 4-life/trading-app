# Swings

The swing indicators: the ones every [strategy chart](dashboard.md#strategy-chart) draws, and [Trendlines with Breaks](#trendlines-with-breaks) with the [Supertrend on its lines](#supertrend-on-the-trendlines) — traded by the [Supertrend strategy](supertrend-strategy-engine.md), whose chart draws its Supertrend.

## Swing Levels

A port of the TradingView "Higher High Lower Low" script, on the paper's timeframe, closed candles only (the last 500):

1. **Pivots** — a pivot high is a candle whose high is above the **4** candles before it and not exceeded by the **4** after it (left / right bars = 4); a pivot low the same with lows. A pivot is known only 4 candles after it happens (on 1h: 4 hours later).
2. **Zigzag clean-up** — a second high in a row that's lower than the previous pivot, a second low in a row that's higher, a low above the previous high and a high below the previous low are dropped.
3. **Labels** — each remaining pivot (`a`) is compared with the previous four alternating pivots (`b` opposite, `c` same, `d` opposite, `e` same kind):

| Label | Condition |
|---|---|
| **HH** higher high | a > b, a > c, c > b, c > d |
| **LL** lower low | a < b, a < c, c < b, c < d |
| **HL** higher low | (a ≥ c and b > c, b > d, d > c, d > e) or (a < b, a > c, b < d) |
| **LH** lower high | (a ≤ c and b < c, b < d, d < c, d < e) or (a > b, a < c, b > d) |

Drawn on the chart; used by [Regime](regime-strategy-engine.md).

## Liquidity Swings

A port of LuxAlgo's "Liquidity Swings" with Pivot Lookback **14**, Swing Area **Full Range**, filtered by **Count > 1** (`backend/app/executors/liquidity_swings.py`):

- A **green swing** is a pivot low with 14 candles on each side; a **red swing**, a pivot high. Its zone is the pivot candle's full range (low → high).
- Each later candle that trades into the zone adds 1 to its count; Pine looks 14 candles back, so the count trails by 14 candles.
- A swing is **confirmed** on the candle where its count first exceeds 1 — when the indicator shows its label. That's usually about 16 candles after the pivot.
- A close beyond the zone (below a green swing, above a red one) **breaks** it.
- The [chart](dashboard.md#strategy-chart) draws confirmed zones as transparent green / red rectangles, from the pivot candle across its count.

## Trendlines with Breaks

A port of LuxAlgo's "Trendlines with Breaks" (`backend/app/executors/trendlines.py`) with swing lookback **14**, slope multiplier **0.5** (the indicator's default: 1 — a flatter line), slope method **ATR** (or the closes' standard deviation, or the linear regression's slope halved — each per candle over 14, × the multiplier). Feeds the [Supertrend](#supertrend-on-the-trendlines); not drawn on the chart yet.

- A pivot high (14 candles each side, so known 14 candles later) starts a **down-trendline** at its price, falling by the slope at its confirmation each candle; a pivot low starts a rising **up-trendline**.
- **Break-up**: a close above the down-trendline projected to that candle; **break-down**: a close below the up-trendline. Once per pivot — a new pivot re-arms it.
- Real-time values (the indicator's *backpaint* off): each line is read as projected to the current candle, so it uses closed candles only. No lines before the first pivots or during the slope's warm-up.

## Supertrend on the Trendlines

A port of the "Supertrend" indicator (`backend/app/executors/supertrend_signals.py`) with its defaults — ATR period **10** (Wilder's), multiplier **3** — run twice, its source (by default `hl2`) replaced by the [trendlines](#trendlines-with-breaks): **one on the upper line, one on the lower line**. Traded by the [Supertrend strategy](supertrend-strategy-engine.md); a Supertrend paper's chart draws the one it trades ([chart](supertrend-strategy-engine.md#chart)).

- An **up band** 3 ATR under the source and a **dn band** 3 ATR over it; each only moves toward the price while the previous close stays on its side.
- The trend turns **down** (Sell) on a close under the previous up band, **up** (Buy) on a close over the previous dn band. The line is the up band in an uptrend, the dn band in a downtrend.
- No value and no signal while the trendline has none (before its first pivot, during the slope's warm-up); a run starts in an uptrend on the next candle with one, without a signal there.

---
[← Back to README](../README.md)
