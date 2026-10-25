from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    """Every setting, read from the environment / `.env` (field name
    upper-cased). Integration keys (Hyperliquid, Telegram) are not
    here - they're set in the app's settings (app/system/integration_keys.py)."""

    model_config = SettingsConfigDict(env_file=".env", extra="ignore")

    # App login (docs/api.md#authentication). Empty = login disabled.
    app_password: str = ""
    # Fernet key encrypting integration keys in the settings table.
    # Empty = settings can't be saved.
    settings_encryption_key: str = ""

    postgres_user: str
    postgres_password: str
    postgres_db: str
    postgres_host: str = "postgres"
    postgres_port: int = 5432
    redis_host: str = "redis"
    redis_port: int = 6379
    # The app's own API, as reached from inside the Docker network (watchdog check).
    api_url: str = "http://api:8000"

    # --- market data (docs/market-data.md) ---
    # The provider (and its URL) is the exchange API selected in the app's
    # settings (app/system/exchange_api.py) - Hyperliquid mainnet without one.
    # Bounds every exchange REST call, so a stalled connection fails fast.
    exchange_request_timeout_seconds: float = 30.0
    # Candle scales collected live for every asset. Paper timeframes must be one of them.
    candle_intervals: list[str] = ["1m", "5m", "15m", "1h", "4h"]
    candle_poll_seconds: int = 60
    funding_poll_seconds: int = 300
    open_interest_poll_seconds: int = 300
    # WebSocket auto-reconnect: check every N s, reconnect after M s without a
    # message. Must stay below the watchdog's market-data freshness threshold.
    ws_health_check_seconds: int = 30
    ws_stale_seconds: int = 120
    # One-shot backfill on every `up`: days of candles (per paper timeframe)
    # and funding history.
    backfill_days: int = 220
    # Trades and order-book snapshots older than this are deleted hourly -
    # only the latest few minutes are ever read (docs/market-data.md#data-retention).
    raw_data_retention_hours: int = 24
    # Scanner papers (docs/papers.md#scanner-papers): coins ranked by 24h volume to
    # scan, and the most single papers one scanner keeps enabled at a time.
    scanner_top_n: int = 40
    scanner_max_active: int = 10

    # --- live trading (docs/execution-engine.md#live-execution) ---
    # Max price move a live market order (an IOC limit order) accepts; beyond
    # it the order doesn't fill and the request fails.
    live_slippage_pct: float = 0.005

    # --- features / executors / execution ---
    # Short on purpose: both are cheap when nothing changed (features are
    # computed once per closed candle), and they decide how fast a candle
    # close becomes a position.
    feature_poll_seconds: int = 5
    executor_poll_seconds: int = 5
    execution_poll_seconds: int = 5

    # --- risk engine (docs/risk-engine.md) ---
    risk_poll_seconds: int = 5
    # Share of a mode's total kept free by the budget allocator.
    budget_reserve_pct: float = 0.10
    # A paper is disabled once its realized loss since (re-)enable reaches
    # this share of its budget - or, for a paper with a backtest, its max
    # drawdown x PAPER_LOSS_BACKTEST_MULTIPLE if that's more.
    paper_loss_disable_pct: float = 0.10
    paper_loss_backtest_multiple: float = 1.25
    # A position is liquidated once margin + unrealized PnL falls to this
    # share of its initial margin. Starting value.
    maintenance_margin_pct: float = 0.20
    # The risk engine liquidates in the execution engine's place only if the
    # execution engine's heartbeat is older than this.
    execution_heartbeat_stale_seconds: int = 30
    # Limits, per mode (share of the mode's total).
    max_position_pct: float = 0.20
    max_correlated_exposure_pct: float = 0.50
    daily_loss_limit_pct: float = 0.05
    kill_switch_drawdown_pct: float = 0.15
    # Groups of assets treated as one exposure, e.g. [["BTC", "ETH"]].
    correlated_asset_groups: list[list[str]] = []

    # --- watchdog (docs/watchdog.md) ---
    watchdog_poll_seconds: int = 60
    market_data_staleness_multiplier: float = 3.0
    disk_usage_max_pct: float = 90.0
    memory_usage_max_pct: float = 90.0
    clock_drift_max_seconds: float = 5.0
    # More queued orders than this in the last minute is a runaway - critical.
    max_orders_per_minute: int = 20
    # An executor with open positions whose last pass is older than this
    # isn't protecting them (SL/TP) - critical.
    executor_heartbeat_stale_seconds: int = 180

    @property
    def database_url(self) -> str:
        return (
            f"postgresql+asyncpg://{self.postgres_user}:{self.postgres_password}"
            f"@{self.postgres_host}:{self.postgres_port}/{self.postgres_db}"
        )


settings = Settings()
