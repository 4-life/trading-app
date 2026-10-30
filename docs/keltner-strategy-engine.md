# Keltner Strategy

A [strategy executor](strategy-executor.md) on the Buy / Sell of the "Keltner Channel signals" TradingView indicator: a Buy opens a **long** and a Sell closes it; a Sell opens a **short** and a Buy closes it — where the paper's direction allows. No stop-loss, no take-profit.

Docker service: `keltner-executor` (`python -m app.executors.keltner`), executor name `keltner`. Directions: **long**, **short** or **both** (either; a close and the opposite entry can fall on the same candle).

## Signals

A port of the indicator's signals with its defaults (`backend/app/executors/keltner_signals.py`), the paper's timeframe, closed candles only (the last 500):

- **Band** — the channel's base, EMA(close, **34**), ± **2** × the standard deviation of the last 34 closes; **%B** — the close's place in it (0 the lower edge, 1 the upper).
- **Support** — %B climbing back over **0**: the previous candle's low. **Resistance** — %B falling back under **1**: the previous candle's high.
- **Buy** — the support level moves (a new support at another price); **Sell** — the resistance level moves.

The indicator's ATR channel and WaveTrend only draw — they make no signals and aren't ported.

| Event on the last closed candle | Flat | Long open | Short open |
|---|---|---|---|
| **Buy** | long / both paper: open **long** (`keltner_buy`) | — | close (`keltner_buy`) |
| **Sell** | short / both paper: open **short** (`keltner_sell`) | close (`keltner_sell`) | — |

- **One entry per signal candle**; signals are checked on candle closes.
- No stop-loss and no take-profit — the opposite signal is the only exit.

## Averaging

An [averaging](papers.md#averaging-papers) Keltner paper adds its own rules to the averaging ones (`backend/app/executors/keltner_averaging.py` — live, demo, backtest and sweep alike). Below for a long; a short is mirrored (green / red swapped, HH for LL, Buy for Sell).

- **Regime** — the paper's [Supertrend](supertrend-strategy-engine.md#chart), as its chart draws it (the lower trendline's for a long paper, the upper's for a short or both one): green bullish, red bearish.
- **Entry** — flat, a **Buy** opens a long only while the Supertrend is **red** (a Sell a short only while it's green). The signal adds take every Buy, whatever the Supertrend; the dip adds, unwinds, give-up and intraday mode are the averaging paper's own.
- **Swing stop** (`swing_stop`) — a candle closing **below the last confirmed LL** (HL ignored) with the position's **whole PnL negative** (its unwinds' realized PnL plus the size held, at that close) closes it there. A position that opened below that LL waits for the next LL confirmed after its entry. After a swing stop the paper waits for the next signal — not the stop's own candle.
- **Broken sell** — with the take-profit reached (not intraday), the position's **first Sell** since its entry is ignored while the Supertrend's line is still at the price it had on the entry candle; any later Sell, or one after the line moved, closes it as usual.
- **Reversal** — a both paper: a long closed on a Sell with the Supertrend green opens a short on that candle (its entry rule), and the other way round.

## Chart

A Keltner paper's [strategy chart](dashboard.md#strategy-chart) draws the signals only — **Buy** (green, under the candle) / **Sell** (red, above it) arrows; no channel, no levels. Other papers' charts don't show them.

## Backtest

**Temporary**, like the [VWAP backtest](vwap-strategy-engine.md#backtest) — same `backtest_trades` table, chart and statistics; run when a paper is [prepared](papers.md#preparation), or by hand after a backfill:

```bash
docker compose -f docker/local/compose.yaml exec keltner-executor python -m app.backtest.keltner [YYYY-MM-DD]
```

- At each signal candle's close: the opening signal opens the position there, the closing one closes it there (both: the opposite entry opens on the same candle).
- `return_pct` — net of both maker fees of the selected provider, as for VWAP; a position still open on the last candle isn't stored.
- An [averaging](papers.md#averaging-papers) paper takes its entries, sells and signal adds from the Buys (long), the Sells (short) or both — each position the direction of its entry — with [its own rules](#averaging) on top.

---
[← Back to README](../README.md)
