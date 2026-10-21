# Watchdog

Docker service: `watchdog`

Monitors all other services and is the mechanism behind the system's resilience goal: safe recovery from VPS restarts, network failures, and individual component failures. Runs on a poll loop (`WATCHDOG_POLL_SECONDS`).

- State (open positions, orders, paper status) is reconstructed from the exchange and persistent storage ([postgres](postgres.md)) on restart, never assumed from memory.
- Failed components are restarted or isolated without a full-stack restart. Process-level restarts use Docker's `restart: unless-stopped` plus healthchecks — the watchdog has no Docker-socket access (that would let it control the whole host).
- As independent from the [strategy executors](strategy-executor.md) as possible — every check queries Postgres, Redis or Hyperliquid directly, so detecting and reacting to a critical violation never depends on an executor being healthy.

## Monitoring

| Check | Severity | What |
|---|---|---|
| `database` | critical | Postgres connectivity |
| `exchange_connectivity` | critical | a live Hyperliquid REST call |
| `clock_drift` | critical | drift vs. Hyperliquid's server time > `CLOCK_DRIFT_MAX_SECONDS` (no NTP/UDP dependency) |
| `order_rate` | critical | more than `MAX_ORDERS_PER_MINUTE` (20) orders queued in the last minute — a runaway executor |
| `live_reconciliation` | critical | open live positions in the database match the Hyperliquid account (skipped without live keys) |
| `position_protection` | critical | every open position belongs to an enabled paper whose executor ran within `EXECUTOR_HEARTBEAT_STALE_SECONDS` (180) — otherwise nothing evaluates its SL/TP |
| `api` | warning | the app's REST API answers `/health` (`API_URL`) |
| `redis` | warning | connectivity |
| `market_data_freshness[<asset>]` | warning | no market data (the newer of the last trade and the last order-book snapshot) for `CANDLE_POLL_SECONDS × MARKET_DATA_STALENESS_MULTIPLIER` — a market without trades for a while (index / stock perps when their market is closed, a quiet coin) still gets book snapshots, so only stopped collection fails |
| `disk` / `memory` | warning | usage > `DISK_USAGE_MAX_PCT` / `MEMORY_USAGE_MAX_PCT` |

Covered elsewhere: WebSocket health — market-data self-reconnects (see [market-data: WebSocket Auto-Reconnect](market-data.md#websocket-auto-reconnect)), the freshness check catches it if that fails; daily loss / drawdown — the [risk-engine](risk-engine.md#limits).

Executors and the execution engine write a heartbeat to [Redis](redis.md) every pass (`heartbeat:<service>`).

## On a Critical Violation

- disable new positions (kill switch)
- if necessary, emergency close — the [execution-engine](execution-engine.md#liquidation) liquidates positions below the maintenance margin
- notify the owner via the Telegram bot

## Kill Switch

A critical failure sets a flag in [Redis](redis.md). While it's set, strategy executors open no new positions. It clears automatically, with a Telegram notification, once the critical checks pass again.

## Observability

Every check pass writes its full results to [Redis](redis.md). The [api](api.md) serves them to the dashboard's [System Health](dashboard.md#system-health) section.

## Alerting

All notifications go through one Telegram bot provider (`backend/app/notifications/`). The bot token and chat id are set in the app's [settings](dashboard.md#settings); without them, alerts are only logged, never dropped silently. Every alert is also recorded in the `system_events` table ([postgres](postgres.md)) before it's sent. **No code in Telegram** (a third party that stores every message): a server error is sent as its message plus the exception's type and first line — no traceback, no file paths — and URLs in any alert lose their query strings (they can carry account ids). The full traceback stays in the service's log on the server (`docker compose … logs <service>`). Messages start with the level's emoji: ℹ️ info, ⚠️ warning, ❌ error, 🚨 critical (e.g. `⚠️ WARNING [watchdog]: …`).

What is sent:

- **Watchdog** — critical violations (kill switch on), recovery (kill switch off), warnings.
- **Risk engine** — papers disabled for losses.
- **Execution engine / risk engine** — liquidations.
- **Trades** — every position **open** and **close** (also partial closes, liquidations and live positions recorded as closed on the exchange), demo and live, sent right after it's committed (`backend/app/notifications/trades.py`). Not held back during a deploy.

  ```
  [DEMO]
  📈 OPEN BTC 1h vwap #12
  long 0.0123

  84,512.30 · margin $34.66 ×3 · green_swing

  SL 84,089.74 · TP 87,892.79

  🟢 balance $9,987.12 · free $9,620.40 · today +$12.40
  ```

  The first line is the mode. An open's mark shows the direction (📈 long, 📉 short); a close's the result (📈 🚀 PnL ≥ 0, 📉 ❌ a loss). A close shows entry → exit price, the reason, and the PnL in $ and % of margin ("so far" for a partial close). The last line's circle is green when `today` ≥ 0, red below. `balance` is the mode's total (demo: cash + reserved margin; live: the account value), `free` the cash not tied up in positions, `today` the realized PnL of positions closed today (UTC).
- **Server errors** — every service logs through the same setup, and anything logged as an error (an unhandled error in an API request, a failed step in a service loop) is sent with its message and the exception's type and first line (no traceback — see above). The same error from the same place is sent at most once per 15 minutes; the next one says how many were suppressed. The API answers such requests with a plain `500`; `4xx` responses are not errors and aren't reported.
- **Crashes** — a service that stops on an unhandled error sends a "crashed" alert before Docker restarts it.

Self-healing never replaces telling the owner.

## Deploys

A deploy restarts every service, which would otherwise produce a burst of irrelevant alerts (errors from services restarting, stale data, the startup kill switch). So the production deploy (`.github/workflows/deploy.yml`) marks it (`backend/app/system/deploy.py`):

1. **Start** — before the stack restarts: Telegram gets "deploy started - alerts paused until it's done". From here on, alerts are still recorded (`system_events`) but not sent.
2. **Finish** — after `docker compose up` (also when the deploy fails).
3. **Summary** — `SETTLE_SECONDS` (150 s) after the finish, the watchdog's next pass sends one message: ℹ️ "deployed - all services up, all checks passing", ⚠️ "deployed - all critical checks passing; warnings: …" (only warning-level checks failing — freshness, memory, disk), or 🚨 "deployed - something is broken: …" (a [critical check](#on-a-critical-violation) failing). Alerts resume.

Every check has a 30 s limit (`CHECK_TIMEOUT_SECONDS`) — one that doesn't answer fails instead of stalling the watchdog, so the summary (and the next passes) always come.

A deploy that doesn't finish within 30 minutes resumes alerts with "deploy didn't finish within 30 min". The marker is a row in `settings` (Postgres survives the restarts); on the very first deploy there's no database yet, so it's skipped.

## VPS Failure Handling

The VPS must be disposable. After completely losing the VPS, a new instance must, in order:

1. Load configuration.
2. Connect to PostgreSQL — restored from the latest manual backup (see [postgres: Backups](postgres.md#backups)); the watchdog does not restore it.
3. Connect to Hyperliquid.
4. Retrieve actual positions.
5. Retrieve open orders.
6. Compare exchange state with local state.
7. Reconstruct state.
8. Verify SL/TP protection.
9. Only then enable trading.

Trading stays disabled until every step has passed — a fresh instance never resumes trading on an assumption.

**Startup gate**: the watchdog sets the kill switch as soon as it starts, and clears it only after a full check pass where every critical check succeeds — Postgres (2), Hyperliquid (3), open positions / orders and SL/TP protection (4, 5, 8). Live positions are compared with the exchange by `live_reconciliation` (6, 7).

---
[← Back to README](../README.md)
