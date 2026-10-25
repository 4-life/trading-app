# Market Data

Docker service: `market-data`

Collects market data. This is the only layer allowed to reach out to exchanges and external data sources — everything downstream consumes its output.

## Providers

Market data comes from the provider of the [exchange API](dashboard.md#exchange-api) selected in the settings — the same one that places live orders, so signals and fills see the same prices. Without an API: **Hyperliquid**. Mainnet only.

| | Hyperliquid | Lighter |
|---|---|---|
| Live trades, order book, candles, quotes | REST + WebSocket | **WebSocket** (`trade/`, `order_book/` — a snapshot, then incremental updates kept in memory, emitted every 5 s — `candle/`, `market_stats/` for best bid / ask) |
| History (backfills), funding, open interest, 24h volume, markets | REST | REST (`candles` — 500 per request, paged; `fundings` — only when an hour passed, since funding settles hourly; `orderBookDetails`) |
| API | `api.hyperliquid.xyz` | `mainnet.zklighter.elliot.ai` |

- `backend/app/exchange/hyperliquid.py`, `lighter.py`; `source.py` picks one.
- **Lighter's REST limit** is 60 requests a minute per IP for a standard account — for every service on the server together — and past it Lighter blocks the IP (HTTP 405) for a while. So on Lighter every process uses one WebSocket for live data (recent candle windows come from its cache, quotes from its market stats), and REST calls share a budget of 45 a minute across all services (a Redis counter); a limit answer (429, 405, 403, or 400 with code 23000) pauses the caller 60 s. A scanner pass or a paper backfill can therefore take a few minutes. The Lighter adapter returns Hyperliquid's shapes, so everything downstream is the same.
- Lighter's funding rate (hourly, in percent, with the paying side) is stored as a signed hourly fraction like Hyperliquid's (> 0: longs pay); it has no premium (stored as 0).
- When the exchange API changes, the long-running services (market-data, scanner, risk engine, execution engine, watchdog) exit within ~15 s and Docker restarts them on the new provider. Stored history isn't touched.

## Asset Universe

The assets are added and deleted in the dashboard's [assets editor](dashboard.md#assets) (the `assets` table; [`/assets`](api.md)) — each a **perpetual** of the provider, by its symbol (e.g. `BTC`). Any symbol is taken as typed: nothing checks the provider lists it (an unlisted one is skipped, below). Market data re-reads the list every 10 s and re-subscribes its WebSocket when it changes — no restart. A new asset is collected from then on; its history comes with a paper's [preparation](papers.md#preparation) backfill. An asset a paper needs can't be deleted: its own papers (a scanner's children too), and any trend paper for `BTC` (the [bear-market filter](trend-strategy-engine.md#bear-market-filter)). Deleting one deletes all its market data — candles, trades, order-book snapshots, funding, open interest and features (once more on the next re-read, for rows stored in between). Migration 0032 seeded the list with the one in use — the old `ASSETS` variable if still set, else the assets collected live (order-book snapshots), else `BTC`, `ETH`, `SOL` — and every paper's own asset.

**One bad asset can't take down collection for the rest**: an asset the provider doesn't list (e.g. Lighter's `XAU` while the data comes from Hyperliquid) is skipped with one warning each time the list is read anew — not collected, not backfilled, not freshness-checked. A paper on it fails its [preparation](papers.md#preparation) with "isn't listed by the market-data provider".

## Collected Data

- trades
- bid/ask
- order book
- OHLCV
- volume
- open interest
- funding
- spreads
- market depth
- exchange timestamps

All timestamps are stored in UTC.

The above is collected for every [asset](#asset-universe) (candles at every `CANDLE_INTERVALS` scale). Coins of enabled papers outside the asset list — the ones a [scanner](papers.md#scanner-papers) picked — get only **candles at their paper's timeframe and 1m** (the 1m close is the current price the portfolio and the risk engine read) **and funding**, polled like the rest (no WebSocket, no order book).

## Data Retention

The market-data service deletes old raw data once an hour; everything else is kept.

| Data | Kept | Why |
|---|---|---|
| trades, order book snapshots | `RAW_DATA_RETENTION_HOURS` (default **24h**) | ~140 MB/day; only the latest few minutes are read (feature engine) |
| candles, features | forever | small (~2 MB/day); backtests and the chart use the whole history |
| funding, open interest | forever | small; demo funding is charged since a position opened |

Positions, orders, decisions and equity snapshots ([postgres](postgres.md)) are never deleted — daily PnL, profitability and the trading log come from them.

## Historical Backfill

A one-shot `backfill` service seeds history on every `docker compose up` (idempotent, only fetches what's missing), so a fresh database doesn't have to wait for live collection. A newly added asset is backfilled automatically on the next `up`.

- **Where an asset's history begins** — an asset listed after the backfill window's start (`BACKFILL_DAYS` ago; e.g. QQQ, SOXL) has nothing before its listing. The first request for the range before its first stored candle finds that out and saves it in `settings` (`candle_history_start:<provider>:<asset>:<interval>`, ms); later runs never request that range again, nor with a longer `BACKFILL_DAYS`. Delete the row to have it requested again.
- **Funding** counts as covered when the stored rows begin within 1 day of the window's start (the provider's first rows come a little after it) — or of where the provider's funding history begins, remembered in `settings` (`funding_history_start:<provider>:<asset>`) by the first backfill that found it later — and reach within 1 hour of now. Not re-fetched in full on every `up`.

Backfill runs only on `up`. It covers the `(asset, timeframe)` pairs of all [papers](papers.md), enabled or disabled — a paper added later gets its history on the next `up` — plus BTC at every [trend](trend-strategy-engine.md#bear-market-filter) paper's timeframe (its bear-market filter). Funding history is backfilled for those assets too.

The backfill window is `BACKFILL_DAYS` (default **220** — the trend strategy's 200-day BTC filter needs it on 4h) for every timeframe and for funding.

On Hyperliquid, `candleSnapshot` retains a fixed **count** of candles per interval, not a fixed number of days. Approximate reach: `1m` ≈ 4 days, `5m` ≈ 16 days, `15m` ≈ 52 days, `1h` ≈ 208 days, `4h` ≈ 830 days. A request past that ceiling silently returns nothing, so a scale whose ceiling is shorter than `BACKFILL_DAYS` is backfilled only up to its ceiling (with the default 220 days: `1m` ≈ 4, `5m` ≈ 16, `15m` ≈ 52 days; `1h` ≈ 208 days).

A paper created later is also backfilled right away by the market-data service's [preparation](papers.md#preparation) loop, without waiting for the next `up`.

Live polling re-fetches the last closed and the forming candle on every poll, so a candle's final values overwrite the ones stored while it was forming.

Backfill requests are chunked by candle count (≈4000 candles per request), not by calendar days.

## Market Limits

Each perpetual's **max leverage** and **maintenance margin** at the selected provider, stored in `market_limits` (provider, asset) by the market-data service on every start (`backend/app/market_data/limits.py`):

- **Lighter** — from `orderBookDetails`, in basis points: max leverage = 10,000 / `min_initial_margin_fraction` (SPY 200 → 50×, QQQ 333 → 30×, HYPE 500 → 20×, BTC 200 → 50×), maintenance margin = `maintenance_margin_fraction` / 10,000 of the notional (SPY 1.2%).
- **Hyperliquid** — each perpetual's `maxLeverage`; maintenance margin is half the initial margin at it (1 / (2 × maxLeverage)).

Used by:

- the **API** — a paper's `leverage` or `add_leverage` above its asset's max is rejected (`422`); the papers list carries `max_leverage` and the dashboard flags a paper over it ("over the max ×50");
- the **averaging backtest** (and the sweep) — the leverages capped at the max, and the **liquidation where the exchange does it**: the equity (margin + the size held's PnL) down to the maintenance share of the notional. At high leverage that's well before 20% of the margin left (`MAINTENANCE_MARGIN_PCT`, still used where no limits are stored): SPY at 50× is liquidated with ~60% of its margin left. The chart's hover shows that liquidation price.

The demo execution engine still liquidates at `MAINTENANCE_MARGIN_PCT` of the margin.

## WebSocket Auto-Reconnect

Hyperliquid only: the SDK's WebSocket manager doesn't reconnect on its own once the socket drops. The collector tracks the time of the last trade/book message and checks it every `WS_HEALTH_CHECK_SECONDS` (default 30s); if nothing arrived for `WS_STALE_SECONDS` (default 120s), it discards the connection, connects fresh and re-subscribes every asset. `WS_STALE_SECONDS` stays below the [watchdog](watchdog.md)'s market-data freshness threshold, so it self-heals before that check fires.

## Rate Limits

All services share one per-IP rate limit at the provider. Every call — candles, funding, open interest, market data, and the client's initial connect — retries with backoff on HTTP 429. Connect gets the most patient retry budget: it runs once at startup, and a failure there kills one-shot services like `backfill`, which blocks the whole stack from starting.

---
[← Back to README](../README.md)
