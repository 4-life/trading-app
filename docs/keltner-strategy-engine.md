# Keltner Strategy

A [strategy executor](strategy-executor.md) on the Buy / Sell of the "Keltner Channel signals" TradingView indicator: a **long** paper buys on a Buy and closes on a Sell, a **short** paper sells on a Sell and closes on a Buy. No stop-loss, no take-profit.

Docker service: `keltner-executor` (`python -m app.executors.keltner`), executor name `keltner`. Directions: **long** or **short** — no both.

## Signals

A port of the indicator's signals with its defaults (`backend/app/executors/keltner_signals.py`), the paper's timeframe, closed candles only (the last 500):

- **Band** — the channel's base, EMA(close, **34**), ± **2** × the standard deviation of the last 34 closes; **%B** — the close's place in it (0 the lower edge, 1 the upper).
- **Support** — %B climbing back over **0**: the previous candle's low. **Resistance** — %B falling back under **1**: the previous candle's high.
- **Buy** — the support level moves (a new support at another price); **Sell** — the resistance level moves.

The indicator's ATR channel and WaveTrend only draw — they make no signals and aren't ported.

| Event on the last closed candle | Flat | Long open | Short open |
|---|---|---|---|
| **Buy** | long paper: open **long** (`keltner_buy`) | — | close (`keltner_buy`) |
| **Sell** | short paper: open **short** (`keltner_sell`) | close (`keltner_sell`) | — |

- **One entry per signal candle**; signals are checked on candle closes.
- No stop-loss and no take-profit — the opposite signal is the only exit.

## Chart

A Keltner paper's [strategy chart](dashboard.md#strategy-chart) draws the signals only — **Buy** (green, under the candle) / **Sell** (red, above it) arrows; no channel, no levels. Other papers' charts don't show them.

## Backtest

**Temporary**, like the [VWAP backtest](vwap-strategy-engine.md#backtest) — same `backtest_trades` table, chart and statistics; run when a paper is [prepared](papers.md#preparation), or by hand after a backfill:

```bash
docker compose -f docker/local/compose.yaml exec keltner-executor python -m app.backtest.keltner [YYYY-MM-DD]
```

- At each signal candle's close: the opening signal opens the position there, the closing one closes it there.
- `return_pct` — net of both maker fees of the selected provider, as for VWAP; a position still open on the last candle isn't stored.
- An [averaging](papers.md#averaging-papers) paper takes its entries, sells and signal adds from the Buys (long) or Sells (short).

---
[← Back to README](../README.md)
