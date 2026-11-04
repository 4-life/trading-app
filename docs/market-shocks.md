# Market Shocks

A detector of sudden market moves — a crash on bad news (an exchange hack), a coin's own rally (good news) — from the candles alone, no news feed (`backend/app/market_data/shocks.py`). Every [strategy chart](dashboard.md#strategy-chart) marks its events, so they can be checked against the real news, and the [risk engine](risk-engine.md#responsibilities) holds back the entries against one for 6 hours: a panic the longs, a bullrun the shorts. The same block holds back an averaging position's signal and strength adds (not its dip adds, which keep it from a margin call). The backtests apply the same block from the same shocks: an averaging paper's backtest and its sweep open no position against one (a reopen in trend neither); a single paper's backtest leaves out the trades it would have held back (not its exit sweep). A Keltner averaging position's strategy sell also waits while a shock in its favour is under 6 hours old ([riding a bullrun](keltner-strategy-engine.md#averaging)). The backtest log lists each entry held back: "paper 94: long entry at 2026-10-29 20:45 held back - market panic (BTC −2.5% in 1h · …, detected 2026-10-29 20:44)".

## Events

From every coin's closed **1m** candles, BTC included — so an event shows within a minute of the move, whatever the chart's timeframe; over the last 14 days (`SHOCK_FINE_SPAN`; every coin's 1m candles are a lot of rows), and only where BTC's 1m candles cover the 4 hours before (they're collected live: before collection began, or across a gap while market-data was down, the chart's own timeframe detects instead):

| Event | When | Chart |
|---|---|---|
| **Market panic** | BTC down fast — **2%** or more within an hour (on BTC volume **4×** its usual), or **3.5%** or more within four hours (volume **2.5×**) — with **70%** of the other coins down in that window too (**1.5%** / **3%** or more); breadth is skipped with fewer than 3 other coins with candles at the timeframe | red dot above the candle, red dashed line |
| **Market bullrun** | the same, up | green dot below the candle, green dashed line |
| **Coin panic** (the chart's coin, not BTC) | its 4h return **5%** or more under BTC's, **3%** or more of it within the last hour (a drop, not a slow slide), on its own volume **3×** its usual | red |
| **Coin bullrun** | its 4h return **5%** or more over BTC's, **3%** or more of it within the last hour (a jump, not a slow climb), on its own volume **3×** its usual | green |

- **Usual volume** — the median candle volume of the 20 windows before (20 hours, or 80), times the candles in the window.
- **Four hours too** — a sell-off can be a slide, not a one-hour crash: the 2026-10-29 Binance hack took BTC −2.5% in its worst hour but −4.2% in four (October's next biggest: −1.6% / −2.0%).
- **Breadth counts the coins with candles at the timeframe** — at 1m, every asset market-data collects (live only, from when it was added); at the chart's timeframe, the papers' assets (backfilled) and the assets editor's.
- **One event of a kind per 6 hours** — its first candle. The dot sits on the chart candle it was detected in; the hover box shows the exact time it was detected (the close of the 1m candle that showed it).
- The hover box shows what triggered it, e.g. "market panic: BTC −3.1% in 1h · 11 of 13 coins down · volume 5.2×".
- A market event shows on every chart; a coin event on that coin's only.

**Telegram** — the risk engine looks for new shocks once a minute (every coin's closed 1m candles) and [alerts](watchdog.md#alerting) each one once (marked in Redis, `shock:alerted:*`): the market's, and every collected coin's own — a panic as a warning, a bullrun as info: "market panic detected 2026-10-29 20:44 UTC: BTC −2.5% in 1h · 6 of 6 coins down · volume 7.9× - new longs held back until 02:44 UTC". Only shocks detected within the last hour are alerted, so a restart doesn't resend old ones — scanned from the 6h cooldown before that hour, so a shock still going isn't taken for a new one every minute (the risk engine's block the same: it runs 6 hours from the shock's first candle).

**Unusual move** — what's unusual depends on the coin, so any coin is also measured against itself: its 30-minute move is **6×** its normal one or more (the standard deviation of its 30-minute moves over the 7 days before) and **1%** at least, with its last 15 minutes of volume **3×** its usual. BTC's is a market event if 70% of the other coins moved 1% the same way (with fewer than 3 others: no breadth check); otherwise it shows on BTC's chart only. Another coin's is a coin event, held back while a market event of its kind is under 6 hours old, so a crash isn't one alert per coin. The hover box reads "ETH −3.1% in 30m · 8.6× its normal · volume 4.2×".

**A move normal for the coin isn't a coin shock**, whatever its volume: a coin's move (the 4-hour one against BTC, or the unusual 30-minute one) must be at least **75%** of its usual day, the median high-to-low of its closes over the 7 days before (at least 3 known; fewer: not filtered). A coin swinging 13% a day needs about 9.5%. Market shocks aren't filtered. On BTC, ETH, BNB and HYPE, 20 of 29 of the moves the 30-minute rule alone flagged over two months cleared 75%, ETH's −2.86% of Oct 7 at 165% of its usual day (15m candles, volume check left out).

The thresholds are constants at the top of the module — tuned once the dots have been checked against the news.

---
[← Back to README](../README.md)
