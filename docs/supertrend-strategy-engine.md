# Supertrend Strategy

A [strategy executor](strategy-executor.md) on the [Supertrend on the trendlines](swings.md#supertrend-on-the-trendlines): a **long** paper trades the Supertrend on the [Trendlines with Breaks](swings.md#trendlines-with-breaks) **lower** line, a **short** paper the one on the **upper** line. No stop-loss, no take-profit.

Docker service: `supertrend-executor` (`python -m app.executors.supertrend`), executor name `supertrend`. Directions: **long** or **short** — no both.

## Signals

The paper's timeframe, closed candles only (the last 500 — the trendlines' pivots and both ATR warm-ups):

| Event on the last closed candle | Flat | Long open | Short open |
|---|---|---|---|
| **Buy** (the trend turns up) | long paper: open **long** (`supertrend_buy`) | — | close (`supertrend_buy`) |
| **Sell** (the trend turns down) | short paper: open **short** (`supertrend_sell`) | close (`supertrend_sell`) | — |

- A long paper only reads the Supertrend on the lower trendline, a short one only the one on the upper trendline: its opening signal opens the position, the opposite one closes it.
- **One entry per signal candle**; signals are checked on candle closes.
- No stop-loss and no take-profit — the opposite signal is the only exit.

## Chart

Every paper's [strategy chart](dashboard.md#strategy-chart) draws a Supertrend — the lower trendline's for a long paper, the upper's for a short or both one (a Supertrend paper's: the one it trades): a 2px line, green in an uptrend, red in a downtrend, and its **Buy** (green, under the candle) / **Sell** (red, above it) arrows; the hover box shows its trend and value. The trendlines themselves aren't drawn. A checkbox under the chart hides it.

## Backtest

**Temporary**, like the [VWAP backtest](vwap-strategy-engine.md#backtest) — same `backtest_trades` table, chart and statistics; run when a paper is [prepared](papers.md#preparation), or by hand after a backfill:

```bash
docker compose -f docker/local/compose.yaml exec supertrend-executor python -m app.backtest.supertrend [YYYY-MM-DD]
```

- At each signal candle's close: the opening signal opens the position there, the closing one closes it there.
- `return_pct` — net of both maker fees of the selected provider, as for VWAP; a position still open on the last candle isn't stored.
- An [averaging](papers.md#averaging-papers) paper (long) takes its entries, sells and signal adds from the Buys and Sells of the lower trendline's Supertrend.

---
[← Back to README](../README.md)
