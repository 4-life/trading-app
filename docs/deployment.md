# Deployment

One VPS runs `docker/production/compose.yaml`. It is prepared once with `scripts/deploy.sh`; after that, every push to `main` is checked, built and deployed by GitHub Actions (`.github/workflows/deploy.yml`). Nothing is built on the VPS.

## VPS Bootstrap (one-time, run manually)

On a fresh Ubuntu/Debian VPS, with a DNS `A` record for your domain pointing at it:

```bash
scp scripts/deploy.sh root@<vps>:/root/
ssh root@<vps> 'bash /root/deploy.sh trading.example.com you@example.com'
```

The script is re-runnable — every step checks before it changes anything. It:

- installs Docker + the Compose plugin
- creates a `deploy` user in the `docker` group (no sudo), with an SSH key for CI
- creates `/home/deploy/trading-app`
- opens only SSH, HTTP and HTTPS via `ufw` (HTTP for the Let's Encrypt challenge and the redirect to HTTPS)
- installs Nginx as the public entry point — it proxies to the dashboard on `127.0.0.1:3000` and passes the visitor's IP in `X-Forwarded-For` (used by the login rate limit)
- issues a Let's Encrypt certificate (Certbot), redirects HTTP → HTTPS, and enables automatic renewal
- prints the values to store as GitHub Actions secrets

The API is not published at all — only the dashboard calls it, over the Docker network. The dashboard's session cookie is `Secure`, so the app only works over HTTPS.

The VPS is disposable (see [watchdog: VPS Failure Handling](watchdog.md#vps-failure-handling)): a new one needs this script, the secrets updated, a re-run of the workflow, and the Postgres backup restored.

## An Existing Server

A server already set up for something else (Nginx, Let's Encrypt, its own SSH port) needs no `scripts/deploy.sh` — only:

- a `deploy` user in the `docker` group that CI can SSH into (`VPS_*` secrets; a key of its own in `~deploy/.ssh/authorized_keys`)
- nothing else on `127.0.0.1:3000`
- the Nginx site proxying the domain to `http://127.0.0.1:3000` over HTTPS with `proxy_set_header X-Real-IP $remote_addr;` (the login rate limit counts it — without it every visitor is Nginx) and HSTS

`APP_DIR` (default `/home/deploy/trading-app`) is created by the first deploy.

## CI/CD (GitHub Actions)

| Job | When | What |
|---|---|---|
| `checks` | every push and pull request | Ruff (lint + format), mypy, backend unit tests, dashboard typecheck |
| `build` | push to `main`, after `checks` | backend and dashboard images → `ghcr.io/<owner>/<repo>-backend` / `-dashboard`, tagged with the commit SHA and `latest`. One backend image serves every backend service, each with its own command. |
| `deploy` | after `build` | writes `.env` from secrets, copies it and `docker/production/compose.yaml` to `APP_DIR` over SSH, then `docker compose pull` + `up -d` (between a [deploy start / finish](watchdog.md#deploys)), prunes old images, and — with `DOMAIN` set — waits up to 5 minutes for `https://<DOMAIN>/login` to answer |

On `up`, Compose's dependency graph runs the one-shot steps first: postgres healthy → `migrate` (`alembic upgrade head`) → `backfill` ([market-data: Historical Backfill](market-data.md#historical-backfill)) → `feature-backfill` → the executors.

Deploys use the `production` GitHub environment (add required reviewers there if deploys should wait for approval).

### Secrets and variables

Settings → Secrets and variables → Actions.

| Secret | From |
|---|---|
| `VPS_HOST`, `VPS_PORT`, `VPS_USER`, `VPS_SSH_KEY` | printed by `scripts/deploy.sh` |
| `POSTGRES_USER`, `POSTGRES_PASSWORD`, `POSTGRES_DB` | your choice |
| `APP_PASSWORD` | the dashboard login password |
| `SETTINGS_ENCRYPTION_KEY` | a Fernet key — generate once, never change it after integration keys are saved |

| Variable (optional) | Default |
|---|---|
| `BACKFILL_DAYS` | `220` |
| `RAW_DATA_RETENTION_HOURS` | `24` |
| `APP_DIR` | `/home/deploy/trading-app` — where the stack lives on the VPS |
| `DOMAIN` | none — the dashboard's domain; set, the deploy ends with a health check on it |

The exchange API and the Telegram keys aren't CI secrets — enter them in the dashboard's [settings](dashboard.md#settings).

### Running compose on the VPS by hand

From `APP_DIR` (`/home/deploy/trading-app`), as `deploy`, always with the `.env` (it holds the image names):

```bash
docker compose --env-file .env -f docker/production/compose.yaml ps
docker compose --env-file .env -f docker/production/compose.yaml logs -f execution-engine
```

## Environments

Local (`docker/local/compose.yaml`, builds from source — one backend image, `trading-app-local-backend`, built by the `migrate` service and reused by every other backend service, the way production runs one CI image) and production (`docker/production/compose.yaml`, runs CI images) run the same services; demo vs. live is a per-paper setting ([papers](papers.md)), not a deployment setting. Each compose file sets an explicit project name so stacks never share volumes.

## Backups

Manual — see [postgres: Backups](postgres.md#backups).

---
[← Back to README](../README.md)
