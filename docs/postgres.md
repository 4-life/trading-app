# Postgres

Docker service: `postgres`

PostgreSQL, accessed via SQLAlchemy 2.0 (async) (see [README: Tech Stack](../README.md#tech-stack)). The system's primary durable store; [Redis](redis.md) holds the kill switch, risk blocks, check results and login rate limits.

## Data

Schema: one initial migration (`backend/migrations/versions/0001_initial_schema.py`); later migrations are small and incremental — `0002` deletes MACD readings for recomputation after the period change, `0003` adds partial exits (`trading_decisions.close_fraction`, `positions.initial_margin_usd`), `0004` adds the temporary `backtest_trades` table (High-Low backtest, since removed), `0005` paper kinds, `0006` `backtest_trades.entry_reason`, `0007` removes the Vortex strategy (its papers with their history, its indicator readings and `vortex_regime_log`), `0008` paper preparation (`papers.prep_status` / `prep_error`), `0009` removes the MACD strategy (its papers with their history and its `macd` / `macd_signal` readings), `0010` removes Alpaca (`reference_prices` and its keys), `0011` adds the `rejected_by_provider` decision outcome, `0012` wipes the market data collected from Lighter testnet (candles, features, funding, trades, order book, open interest, backtest trades) after testnet support was dropped.

| Table | Content |
|---|---|
| `candles`, `trades`, `order_book_snapshots`, `funding_rates`, `open_interest_snapshots` | market data |
| `features` | features per `(asset, interval, name, computed_at)` |
| `papers` | papers; one enabled live paper per asset (partial unique index) |
| `demo_balance` | the demo balance, single row, seeded $5000 |
| `positions` | open and closed positions, both modes; one open position per paper |
| `orders` | orders and fills, both modes |
| `trading_decisions` | the decision log (below) |
| `equity_snapshots` | equity curve per mode (and per paper) for drawdown / daily loss |
| `settings` | integration keys (encrypted) |
| `risk_events`, `system_events` | risk-engine and watchdog events |

This is what the [watchdog](watchdog.md) reconstructs state from after a restart.

## Schema Migrations

Managed with Alembic. Run automatically on `docker compose up` by a one-shot `migrate` service (`alembic upgrade head`): it waits for Postgres to be healthy, and every other service waits for it to finish — see [deployment](deployment.md#cicd-github-actions).

## Backups

Backups are manual (operator-run). Surviving a full VPS loss (see [watchdog: VPS Failure Handling](watchdog.md#vps-failure-handling)) requires restoring the latest backup onto the new Postgres instance before the rest of the stack starts.

## Trading Decision Log

Every decision a [strategy executor](strategy-executor.md) makes — entry, exit, add — is recorded, placed or not. The table is also the **order queue**: `outcome` goes `pending` (executor) → `approved` / `rejected_by_risk` (risk engine) → `placed` / `failed` (execution engine). A paper has at most one `pending`/`approved` row at a time.

- timestamp
- paper
- mode (demo / live)
- asset
- feature snapshot
- signal (enter / exit / add — a unit added to the open position, [averaging down](papers.md#averaging-papers)) + direction + the executor's reason
- confidence / score
- risk decision + reason
- position size
- entry / SL / TP prices
- final decision (outcome)

Required for later analysis, and it backs the dashboard's [Trading Log](dashboard.md#trading-log): the reason field answers why the system entered, exited, rejected a trade, or chose a position size. Secrets never appear in it.

## Data Retention

Only trades and order book snapshots are deleted, after `RAW_DATA_RETENTION_HOURS` (default 24h) — see [market-data](market-data.md#data-retention). Every other table is kept. Postgres reuses the freed space instead of returning it to the disk, so the database levels off rather than shrinking.

---
[← Back to README](../README.md)
