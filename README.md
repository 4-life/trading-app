# Trading App

An autonomous trading system with manual control for cryptocurrencies and tokenized equities.

## Core Concept

Easy to run hardcoded strategies on a decentralized exchange. Control over several strategies, monitoring, and manual retiring of ineffective strategies — the strategy is a replaceable component, and risk and security sit above it.

## Goals

- Trade cryptocurrencies and tokenized equities.
- Run 24/7 on a VPS.
- Continuously collect market data from the selected exchange (Hyperliquid or Lighter).
- Run complicated independent strategy engines.
- Automatically disable papers that are losing their budget (by the risk engine).
- Run an independent risk engine that cannot be overridden by others.
- Recover safely from VPS restarts, network failures, and individual component failures.
- Never store the seed/private key of the main wallet on the VPS.

## Tech Stack

- **Backend / trading system**: Python.
- **API**: FastAPI, served by Uvicorn.
- **Database**: PostgreSQL, accessed via SQLAlchemy 2.0 (async).
- **Dashboard**: React, server-side rendered (SSR). See [dashboard](docs/dashboard.md).
- **Deployment**: everything runs in Docker (the VPS runs the Docker Compose stack). See [deployment](docs/deployment.md).

## Local Development

Runs the full stack on your machine from source (`docker/local/compose.yaml`). Real market data, no real orders unless a paper is switched to live.

```bash
cp .env.example .env
# edit .env (see below), then:
docker compose -f docker/local/compose.yaml up -d --build
```

In `.env` (`.env.example` documents every variable):

| Variable | |
|---|---|
| `APP_PASSWORD` | the dashboard login — required |
| `SETTINGS_ENCRYPTION_KEY` | required to save the exchange API and Telegram keys in Settings; generate once: `python -c "from cryptography.fernet import Fernet; print(Fernet.generate_key().decode())"` |
| `POSTGRES_USER` / `POSTGRES_PASSWORD` / `POSTGRES_DB` | the local database — any values |
| `ASSETS` | perpetuals collected live, e.g. `["BTC","ETH","SOL"]` |
| `BACKFILL_DAYS` | candle history fetched on every `up` (220) |
| `API_PORT` / `DASHBOARD_PORT` | 8000 / 3000 |

The other variables have working defaults.

- Migrations run automatically before the services start — no manual `alembic upgrade` step.
- Dashboard: http://localhost:3000 — API: http://localhost:8000 (`/health`) — Postgres: `localhost:5432`. All bound to `127.0.0.1`: this machine only, not the network.
- After a code change, the same `up -d --build` rebuilds and restarts.

## Production Deploy

Every push to `main` is checked, built and deployed by GitHub Actions (`.github/workflows/deploy.yml`): Ruff, mypy, the unit tests and the dashboard typecheck → backend and dashboard images to `ghcr.io` → over SSH to the VPS, `docker compose pull` + `up -d`, then a health check on `https://<DOMAIN>/login`. Nothing is built on the VPS, and its `.env` is written by CI from the secrets below on every deploy — don't edit it there.

The VPS is prepared once: a fresh one with `scripts/deploy.sh` (Docker, a `deploy` user, Nginx + Let's Encrypt), or an existing one by hand — see [deployment](docs/deployment.md).

GitHub → Settings → Secrets and variables → Actions:

| Secret | |
|---|---|
| `VPS_HOST` / `VPS_PORT` / `VPS_USER` | the server's IP, its SSH port, `deploy` |
| `VPS_SSH_KEY` | the `deploy` user's private SSH key (its public key in `~deploy/.ssh/authorized_keys`) |
| `POSTGRES_USER` / `POSTGRES_PASSWORD` / `POSTGRES_DB` | the production database |
| `APP_PASSWORD` | the dashboard login (until changed in Settings — then the database's hash) |
| `SETTINGS_ENCRYPTION_KEY` | a Fernet key — **never change it** once keys are saved in Settings, or they can't be decrypted |

| Variable | Default |
|---|---|
| `DOMAIN` | none — the dashboard's domain; set, the deploy ends with a health check on it |
| `ASSETS` | `["BTC","ETH","SOL"]` |
| `BACKFILL_DAYS` | `220` |
| `RAW_DATA_RETENTION_HOURS` | `24` |
| `APP_DIR` | `/home/deploy/trading-app` |

The exchange API and the Telegram keys aren't GitHub secrets — enter them in the dashboard's Settings.

## Papers & Trading Modes

The core of the app is paper management: a paper is one strategy running on one asset, created and controlled by the owner. Every paper runs in **demo** or **live** mode, both modes run at the same time, each with its own budget. There is no separate dev/prod build — the app is always deployed the same way.

See [papers](docs/papers.md).

## VPS Architecture

Deployed as a Docker Compose stack of independent services, mirroring the layers below. Each service has its own doc:

- [market-data](docs/market-data.md) — market data.
- [feature-engine](docs/feature-engine.md) — normalized features across price, volume, derivatives, order book, and tokenized-equity domains.
- [strategy-executor](docs/strategy-executor.md) — can be many containers; each is a dedicated, hardcoded strategy ([VWAP + EMA9](docs/vwap-strategy-engine.md), [Trend](docs/trend-strategy-engine.md), [Regime](docs/regime-strategy-engine.md) or [Supertrend](docs/supertrend-strategy-engine.md)) run independently across every configured asset; the [swing indicators](docs/swings.md) they and the chart share.
- scanner — finds coins across the market for [scanner papers](docs/papers.md#scanner-papers) and creates papers for them.
- [risk-engine](docs/risk-engine.md) — sits above all containers: checks risk and budget in real time, approves every new position, can stop any executor from opening positions, disables papers that are losing their budget.
- [execution-engine](docs/execution-engine.md) — the exchange abstraction, Hyperliquid integration, demo execution, and wallet key custody.
- [watchdog](docs/watchdog.md) — resilience: recovery from restarts, network failures, and component failures.
- [api](docs/api.md) / [postgres](docs/postgres.md) / [redis](docs/redis.md) — supporting services. Postgres is the durable store; Redis holds the kill switch, risk blocks, watchdog check results and login rate limits.

[budget-allocator](docs/budget-allocator.md) is **not** a separate service — a shared library module that reads available balance and sizes every position from leverage, asset and fees, for both demo and live budgets.

The system is built as independent layers, each replaceable and individually testable:

```
          Risk Engine (above everything, real time, cannot be overridden)
                │ approves every new position · blocks executors · disables papers
                ▼
Market Data → Feature Engine → Strategy Registry + Executors → Execution Engine
                                                                ├─ Demo trading (simulated)
                                                                └─ Live trading → Hyperliquid (via Exchange Adapter)
```

## Testing

Unit tests, integration tests, simulation, and chaos testing are mandatory. See [testing](docs/testing.md).

## Trading Venue

Primary execution platform: **Hyperliquid**, accessed through an exchange-agnostic `ExchangeAdapter` so another venue can be added later. See [execution-engine](docs/execution-engine.md).

## Security

- Single owner: the app runs on a remote VPS and only the owner uses it. Entering the app requires a password; the password is a secret in `.env` / GitHub secrets until the owner changes it in the app's settings — then its salted hash in the database takes over ([api: Authentication](docs/api.md#authentication)).
- The exchange API (Hyperliquid or Lighter) and the Telegram bot keys are entered in the app's settings and stored in the database. See [dashboard: Settings](docs/dashboard.md#settings).
- Infrastructure secrets are never committed to the repo — `.env` is git-ignored; `.env.example` documents which variables are required, without real values.
- Secrets are injected via environment variables / Docker secrets, never hardcoded in source.
- Secrets are never logged or included in error messages, system events, or the [Trading Decision Log](docs/postgres.md#trading-decision-log); alerts also redact anything shaped like a key or token (`app/notifications/alerts.py` `redact`).
- The login rate limit counts the visitor's real IP — Nginx's `X-Real-IP` (it overwrites a client-sent one), never the client-controlled start of `X-Forwarded-For`.
- Log out revokes the session token at the API, not only the cookie.
- The dashboard sends `X-Frame-Options: DENY`, `frame-ancestors 'none'`, `nosniff` and `Referrer-Policy: same-origin`; production Nginx adds HSTS.
- The containers run as unprivileged users (`app` uid 10001, `node`), not root. Form ids reach the API as digits only.
- Exchange API credentials are scoped to trading only — no withdrawal permission — so a leaked key cannot move funds out of the account.
- The main wallet's seed/private key is never stored on the VPS; see [execution-engine: Key Custody](docs/execution-engine.md#key-custody).

### Required Secrets

`APP_PASSWORD`, `SETTINGS_ENCRYPTION_KEY` and the Postgres credentials — in `.env` locally ([Local Development](#local-development)), as GitHub secrets in production ([Production Deploy](#production-deploy)). Redis has no password: it's reachable only inside the Docker network.

## Asset Universe

Configured via `ASSETS` — perpetuals of the selected provider (see [market-data: Asset Universe](docs/market-data.md#asset-universe)). Default: `["BTC"]`; scanner papers add the coins they pick.
