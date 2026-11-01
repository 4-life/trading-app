# Market Shocks

A detector of sudden market moves — a crash on bad news (an exchange hack), a coin's own rally (good news) — from the candles alone, no news feed (`backend/app/market_data/shocks.py`). Every [strategy chart](dashboard.md#strategy-chart) marks its events, so they can be checked against the real news, and the [risk engine](risk-engine.md#responsibilities) holds back the entries against one for 6 hours: a panic the longs, a bullrun the shorts. The backtests don't apply that block.

## Events

From every coin's closed **1m** candles, BTC included — so an event shows within a minute of the move, whatever the chart's timeframe; over the last 14 days (`SHOCK_FINE_SPAN`; every coin's 1m candles are a lot of rows), and only where BTC's 1m candles cover the 4 hours before (they're collected live: before collection began, or across a gap while market-data was down, the chart's own timeframe detects instead):

| Event | When | Chart |
|---|---|---|
| **Market panic** | BTC down fast — **2%** or more within an hour (on BTC volume **4×** its usual), or **3.5%** or more within four hours (volume **2.5×**) — with **70%** of the other coins down in that window too (**1.5%** / **3%** or more); breadth is skipped with fewer than 3 other coins with candles at the timeframe | red dot above the candle, red dashed line |
| **Market bullrun** | the same, up | green dot below the candle, green dashed line |
| **Coin panic** (the chart's coin, not BTC) | its 4h return **5%** or more under BTC's, on its own volume **3×** its usual | red |
| **Coin bullrun** | its 4h return **5%** or more over BTC's, on its own volume **3×** its usual | green |

- **Usual volume** — the median candle volume of the 20 windows before (20 hours, or 80), times the candles in the window.
- **Four hours too** — a sell-off can be a slide, not a one-hour crash: the 2026-10-29 Binance hack took BTC −2.5% in its worst hour but −4.2% in four (October's next biggest: −1.6% / −2.0%).
- **Breadth counts the coins with candles at the timeframe** — at 1m, every asset market-data collects (live only, from when it was added); at the chart's timeframe, the papers' assets (backfilled) and the assets editor's.
- **One event of a kind per 6 hours** — its first candle. The dot sits on the chart candle it was detected in; the hover box shows the exact time it was detected (the close of the 1m candle that showed it).
- The hover box shows what triggered it, e.g. "market panic: BTC −3.1% in 1h · 11 of 13 coins down · volume 5.2×".
- A market event shows on every chart; a coin event on that coin's only.

The thresholds are constants at the top of the module — tuned once the dots have been checked against the news.

---
[← Back to README](../README.md)
