# Feature Engine

Docker service: `feature-engine`

Consumes the output of [market-data](market-data.md) and turns it into normalized features for the [strategy executors](strategy-executor.md) and the [risk-engine](risk-engine.md). Never touches raw exchange/data-source connections directly.

Features are computed from **closed candles only**, once per closed candle, stamped at that candle's close time, and stored in [postgres](postgres.md). A candle counts as closed once the next one has been collected. A one-shot feature backfill computes historical features from the backfilled candle history on startup (see [deployment](deployment.md)), so strategies have indicator history from the first run. It only computes the timestamps no earlier run did (one `DISTINCT computed_at` query per asset and timeframe): a historical value never changes, so a timestamp with any features is done, even where some feature had no value (too little history at the start).

Features are computed live per `(asset, timeframe)` of the enabled [papers](papers.md); the backfill covers all papers, enabled or disabled (see [market-data](market-data.md#historical-backfill)).

## Features by Domain

**Price**
- returns: 1m / 5m / 15m / 1h / 4h / 1d
- momentum
- volatility
- ATR
- distance from highs/lows
- breakout distance

**Volume**
- volume z-score
- relative volume
- volume acceleration

**Derivatives**
- open interest
- OI change
- funding
- basis

**Order Book**
- bid/ask imbalance
- market depth
- spread
- aggressive buy/sell ratio

**Tokenized Equities**
- premium/discount vs. reference asset
- overnight return
- distance from official close
- distance from reference opening price

---
[← Back to README](../README.md)
