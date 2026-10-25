# Testing

Mandatory across the system — not optional, not deferred to "later".

## Static Checks

All Python code is linted/formatted with [Ruff](https://docs.astral.sh/ruff/) and type-checked with [mypy](https://mypy-lang.org/) (`strict = true`). These run before unit tests, not instead of them.

## Unit Tests

Pure functions, no database or Docker (`backend/tests/test_*.py` except `test_pipeline.py`):

- strategy rules — swing labels, Trend breakout / trailing stop / 1% stop-loss / bear filter, paper direction
- budget allocator, risk limits (incl. per-mode capital, drawdown)
- demo execution — fill price, margin with leverage, PnL, funding, liquidation threshold, profitability
- API — login tokens, unrealized PnL

```bash
cd backend && uv run pytest tests --deselect tests/test_pipeline.py
```

## Integration Tests

`scripts/e2e-test.sh` (from the repo root) runs `backend/tests/test_pipeline.py` in a throwaway stack (`docker/test/compose.yaml`, separate project name — never shares volumes with a running stack), against **real Hyperliquid data**:

1. Fresh `postgres` + `redis` → `migrate`.
2. `e2e-tests` runs the pipeline in order — later steps depend on earlier ones:
   - login (and a wrong password), create a paper (and a rejected short VWAP paper)
   - market-data backfill for the paper, then feature backfill (ATR and momentum present)
   - one pass of each executor
   - a known entry → risk engine approves and sizes it → execution engine fills it
   - `/portfolio` shows the position; live has "no live data"
   - manual close through the API → risk → execution; profitability updated
   - liquidation below the maintenance margin
   - watchdog pass records every check, `/system-health` serves them
   - `/decisions` pagination, `/settings` encryption + masking, `/auto-open`
   - paper lifecycle: go-live refused with negative profitability, disable/enable, delete
   - demo reset (last) clears everything demo
3. `docker compose -f docker/test/compose.yaml down -v` always runs on exit, pass or fail.

The stack uses test-only `APP_PASSWORD` / `SETTINGS_ENCRYPTION_KEY` (set in the compose file) and a 3-day backfill. Needs `.env` (Postgres credentials; the test adds `BTC` to the assets) and outbound access to Hyperliquid.

## Simulation

Simulate:
- exchange unavailable
- network loss
- duplicate order
- stale data
- partial fill
- VPS restart
- database failure
- API timeout

## Chaos Testing

Simulate:
- kill VPS
- disconnect network
- kill WebSocket
- kill Redis
- restart database
- duplicate execution message
- delay exchange response

The bot must recover safely — see [watchdog](watchdog.md) for the recovery sequence these scenarios exercise.

---
[← Back to README](../README.md)
