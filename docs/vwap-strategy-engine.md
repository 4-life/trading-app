# VWAP + EMA9 Strategy

A [strategy executor](strategy-executor.md) built on the TradingView indicator "VWAP + EMA9 With Signals" — the signals alone: a candle closing **above both the session VWAP and EMA 9** (BUY) opens a long, **below both** (SELL) closes it; with direction **both**, a SELL also opens a short and a BUY closes it. No stop-loss, no zones.

Docker service: `vwap-executor` (`python -m app.executors.vwap`), executor name `vwap`. Directions: **long** or **both** (long + short). Meant for **15m** or **1h** papers (leverage set on the paper).

## Lines

The paper's timeframe, closed candles only (the last 500):

- **VWAP** — volume-weighted average of the typical price (high + low + close) / 3, **reset every UTC day** (the indicator's "Session" anchor; crypto has no sessions). No volume yet in the day → no VWAP, no signal.
- **EMA 9** of the closes.

## Signals

Non-repeating, as in the indicator — a signal fires on the candle whose close **moves** past both lines, not on every candle that stays there:

- **BUY** — the close above both EMA 9 and the VWAP; the previous candle's close wasn't.
- **SELL** — the close below both; the previous candle's close wasn't.

BUY and SELL don't strictly alternate: a close going above both, then between the lines, then above both again gives two BUYs.

| Event | Flat | Long open | Short open |
|---|---|---|---|
| **BUY** on the last closed candle | open **long** | — | close (`buy_signal`) |
| **SELL** on the last closed candle | open **short** (direction both) | close (`sell_signal`) | — |

- **One entry per signal candle**, on its close. Signals are checked on candle closes.
- No stop-loss and no take-profit.

## Decision Log Reasons

| Reason | |
|---|---|
| `buy_signal` | a long entry, or a short closed |
| `sell_signal` | a short entry, or a long closed |

## Chart

The [strategy chart](dashboard.md#strategy-chart) of every paper draws the **VWAP** (orange) and **EMA 9** (blue) and the **BUY** (blue, under the candle) / **SELL** (red, above it) signals, computed exactly as the executor does. The chart's first, partial day has no VWAP line and no signals.

## Backtest

**Temporary** — for evaluating the strategy; dropped with a later migration once that's done. Run when a paper is [prepared](papers.md#preparation), or by hand after a backfill:

```bash
docker compose -f docker/local/compose.yaml exec vwap-executor python -m app.backtest.vwap [YYYY-MM-DD]
```

`python -m app.backtest.vwap` replays these rules over every VWAP paper's stored candles (closed only, the whole history) and replaces the paper's rows in the `backtest_trades` table. It logs each paper's totals. Trading starts on the given date — the **whole stored history** by default.

- At each signal candle's close: the opposite position closes there, and — flat, direction allowing — the signal's opens there.
- A position still open on the last candle has no result yet, so it isn't stored — it's left out of the chart, the summary and every statistic (and the [loss limit](risk-engine.md)).
- `return_pct` — long or short, net of both **maker** fees of the selected provider (Hyperliquid 0.015% per side, Lighter none; Hyperliquid without an exchange API — every order, stops included, is a limit order), % of the entry notional (× leverage = % of margin; × 10 at 10×). The spread isn't included.
- The chart's summary shows the totals in % of price, the result **compounded at the paper's leverage** (each trade on the whole margin) with its **max drawdown**, and a **month-by-month** split.

The [strategy chart](dashboard.md#strategy-chart) draws the trades and their totals.

---
[← Back to README](../README.md)
