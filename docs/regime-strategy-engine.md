# Regime Strategy

A [strategy executor](strategy-executor.md) that holds the trend: a [trend-band](#trend-bands) flip opens the position, and the opposite flip closes it. Pullbacks inside the trend don't matter. A short also closes **at the bottom** (a confirmed HH), where a long takes over. A long also closes on a **rejection at the last 4h HH**, or on a **new 4h LL**. A far **disaster stop** keeps the position out of liquidation.

Docker service: `regime-executor` (`python -m app.executors.regime`), executor name `regime`. Directions: long / short / both. Meant for **1h** papers at **2–3× leverage**, not 10×. The exit comes about 6 ATR(100) from the entry band (often 8–15% on 1h crypto), and pullbacks inside a trend can be that deep.

## Trend Bands

A port of BigBeluga's "Dynamic Trend Bands & Anchored VWAP Signals" with its default settings (`backend/app/executors/trend_bands.py`), on the paper's timeframe, closed candles only (the last **5000**, the indicator's own `calc_bars_count`: the trend depends on the whole path):

- **Baseline**: an EMA 50 of an EMA 50 of the closes. **ATR**: 100 candles (Wilder). **Bands**: baseline ± 3 × ATR.
- **Warm-up**: no bands, and so no trend or signals, for the first **300** candles of the history, until the double EMA (seeded with the first close) and the ATR settle. Otherwise a backtest's first trades come from unsettled bands. Live trading computes over 5000 candles and isn't affected.
- **Trend**: **bullish** from a close crossing above the upper band, **bearish** from a close crossing below the lower band. Neutral before the first cross. The baseline lags about 50 candles and the price has to travel 3 ATR, so a flip comes well after the turn. It works as a filter, not as a trigger.
- **Value zone**: the active band's inner ATR (drawn on the chart, not traded): lower band → lower band + ATR while bullish, upper band − ATR → upper band while bearish.
- **Break-up** (bullish only): a pivot high (**10** candles each side, known 10 candles later) confirmed while the trend was already bullish 10 candles before arms the signal. The first later close at or above the VWAP of the highs, anchored at the latest local high (the highest of the last 10 candles), fires it. One signal per pivot, and a trend flip disarms it. **Break-down** is the same on the lows.

## Signals

The paper's timeframe, closed candles only:

| Event | Flat | Long open | Short open |
|---|---|---|---|
| the trend bands **flip bullish**, or a band **break-up** while bullish | open **long** | — | close (`regime_flip`), then the long on the same candle |
| the trend bands **flip bearish**, or a band **break-down** while bearish | open **short** (direction both / short; not while [waiting after a false bottom](#false-bottom)) | close (`regime_flip`), then the short on the same candle | — |
| an **HH** confirmed since the short's entry | — | — | close (`bottom_exit`), then the [reversal long](#bottom-exit) on the same candle |
| a candle reaches the last [4h HH](#4h-swings) confirmed since the long's entry and closes under it | — | close (`hh_rejection`) | — |
| a **4h LL** confirmed since the long's entry | — | close (`top_exit`; a reversal long before the bands turned bullish: `false_bottom`) | — |
| price through a reversal long's stop, before the bands turned bullish | — | close (`false_bottom`) | — |
| after a false bottom, a new **4h LL** confirmed, the close above it, bands not bullish | open **long** (`ll_rebuy`) | — | — |
| price **10%** against the entry | — | close (`disaster_stop`) | close (`disaster_stop`) |

- The trend signal: the bands flip in the trade's direction, or a band break while the trend holds; entered at once on that candle's close.
- `regime_flip` closes a position once the bands, having been in its direction since the entry, leave it.
- **One entry per signal candle**: after a stop, the next entry needs a new signal.
- Stops are recorded on the entry and checked every executor pass (5 s) against the **latest trade price** (the last closed candle's close if no trade arrived in the last 60 s). Every other exit is checked on candle closes.
- **Disaster stop**: 10% is 30% of margin at 3× and 20% at 2×, so it triggers before liquidation (about 33% at 3×). At 10× it would come after liquidation, so don't run this executor at 10×.

### Bottom Exit

A sell-off usually bottoms in a V, far below the upper band, so waiting for the bullish flip gives back much of the move. Instead, a short closes on the first **HH** confirmed after its entry (1h swing pivots 4 candles each side, so known 4 candles after the high): the lower-high / lower-low structure is broken.

- With direction **both**, a long opens at once (`reversal_entry`), its stop under the **sell-off's low**: the lowest low since the short's entry candle, at most the disaster stop (10%) away. A fixed 2% stop sat inside the noise of a bottom's retest (backtest: 19 of 19 stopped).
- Once the bands turn bullish, it's a regular long: its stop gives way to the disaster stop, and the regime flip, HH rejection and 4h LL close it.

### False Bottom

A reversal long stopped, or closed by a new 4h LL, before the bands turned bullish is a **false bottom** (`false_bottom`): the sell-off resumed.

- From then on, **no short opens**, and the long is re-bought at each new **4h LL** confirmed while the bands aren't bullish (`ll_rebuy`), provided the candle closes above it. Its stop is **half an ATR(100) under that LL**, not at it: a stop exactly at the low gets swept by its retest.
- Stopped again before the bands turn bullish, it's another false bottom, and the next 4h LL re-buys again (no limit).
- The wait ends when a long opens: a re-buy, or a regular entry on the bullish flip.

### Long Exits

Besides the regime flip, which comes about 6 ATR from the top, every long (reversal longs included) has two structure exits on the [4h swings](#4h-swings):

- **HH rejection** (`hh_rejection`): a candle (1h) reaches the last 4h HH confirmed after the long's entry and closes under it. The run failed to break its high.
- **Top exit** (`top_exit`): a 4h LL is confirmed after the long's entry. The run's higher lows broke: the mirror of the shorts' bottom exit.

### 4h Swings

The HH / LL labels of the false-bottom re-buys and the long exits come from 4h candles built from the paper's 1h candles (UTC boundaries, complete ones only), with the [swing rules](swings.md#swing-levels) (pivot 4 each side, so known 4 four-hour candles, 16 hours, after the high or low). No extra data is needed. The bottom exit uses the paper's own (1h) swings.

## Decision Log Reasons

| Reason | |
|---|---|
| `regime_entry` | long or short entry on the trend signal |
| `reversal_entry` | the long opened at a short's bottom exit |
| `ll_rebuy` | after a false bottom: the long re-bought at a new 4h LL |
| `regime_flip` | the trend bands left the trade's regime |
| `bottom_exit` | a short closed: an HH confirmed since its entry |
| `hh_rejection` | a long closed: the last 4h HH reached, closed under |
| `top_exit` | a long closed: a 4h LL confirmed since its entry |
| `false_bottom` | a reversal long stopped, or closed by a 4h LL, before the bands turned bullish |
| `disaster_stop` | the 10% stop |

## Backtest

**Temporary**, like the [VWAP backtest](vwap-strategy-engine.md#backtest): same `backtest_trades` table, chart and statistics. It runs when a paper is [prepared](papers.md#preparation), or by hand after a backfill:

```bash
docker compose -f docker/local/compose.yaml exec regime-executor python -m app.backtest.regime [YYYY-MM-DD]
```

- An entry candle opens the position at its close.
- A candle trading through the stop (from the candles closed before it: a reversal long's own, under the sell-off's low or the 4h LL, until the bands turn bullish; else the disaster stop) closes the position there (at the open if it opened past it), filling **0.05% further**. Otherwise an exit at its close closes the position at that close: after a bottom exit the reversal long opens there; after a regime flip the same candle opens the opposite position, direction allowing.
- After a false bottom, no short opens until a long does.
- **Pyramiding test** (backtest only, temporary: the execution engine allows one entry per position, so the live executor doesn't add). A long adds an equal unit each time a candle closes above the last 4h HH confirmed since its entry, with the bands bullish: one add per HH, at most **3 units**. Each add moves every unit's stop under the last 4h HL confirmed by then (never down; exit reason `pyramid_stop`). All units close together on the position's exit. Each unit is stored as its own trade (entry reason `pyramid_add`), so the summed % of price is the pyramid's result in units. The chart's compounded and drawdown figures assume trades one after another, so they're wrong while units overlap.
- `return_pct`: net of both maker fees of the selected provider, as for VWAP. A position still open on the last candle isn't stored.

---
[← Back to README](../README.md)
