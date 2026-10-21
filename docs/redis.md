# Redis

Docker service: `redis`

Used for:
- rate limiting password login to the app (see [README: Security](../README.md#security))
- the [watchdog](watchdog.md#kill-switch) kill switch
- the dashboard's live [auto-trading switch](dashboard.md#live-cards) (`live:auto_trading`, missing = off)
- [risk-engine](risk-engine.md) blocks
- the watchdog's latest check results
- service heartbeats (`heartbeat:<service>`) — executors and the [execution-engine](execution-engine.md#liquidation)

Redis keeps **nothing on disk** (`--save "" --appendonly no`): every start begins empty. That is what turns live auto-trading off after a restart; everything else here is re-set by the services within one pass (the watchdog sets the kill switch as it starts).

Everything else — papers, positions, settings — lives in [Postgres](postgres.md).

---
[← Back to README](../README.md)
