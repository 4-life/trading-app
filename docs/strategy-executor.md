# Strategy Executor

Docker service: one container per strategy.

Each executor is a dedicated, hardcoded strategy. Strategies are replaceable components: adding a strategy means adding an executor container; nothing else changes.

## Strategies

- [Trend](trend-strategy-engine.md) — 20-day breakout ridden with a 3 × ATR trailing stop under a 1% stop-loss (1m candles); shorts only in a BTC bear phase.
- [VWAP + EMA9](vwap-strategy-engine.md) — a close moving above both the daily VWAP and EMA 9 opens a long, below both closes it (and, with direction both, opens a short; a BUY closes that). No stop-loss. Long / both.
- [Supertrend](supertrend-strategy-engine.md) — the Supertrend on the Trendlines with Breaks: a long paper buys on a Buy of the one on the lower line and closes on its Sell, a short paper sells on a Sell of the one on the upper line and closes on its Buy. No stop-loss, no take-profit. Long / short.
- [Regime](regime-strategy-engine.md) — holds the trend: a BigBeluga trend-band flip opens the position, the opposite flip closes it; a short closes at the bottom (a confirmed HH) where a long takes over (stop under the sell-off's low, re-bought at new 4h LLs after a false bottom); a long also closes on a rejection at the last 4h HH or a new 4h LL; 10% disaster stop. Meant for 2–3×.

## Responsibilities

- Run independently across every paper's asset ([asset universe](market-data.md#asset-universe)).
- Run the [papers](papers.md) attached to it (`paper.executor` = this executor's name), each in its own mode (demo or live) and within its `direction` (long / short / both).
- Read features from the [feature-engine](feature-engine.md) — never market data sources or the exchange directly.
- Decide the market regime on its own, if the strategy needs one. There is no system-wide regime.
- Read the paper's candles and features at `paper.timeframe` — **closed candles only**. The forming candle is never used for a signal or a price check (SL/TP).
- Queue every signal (enter / exit, direction, reason) as a `pending` row in the [Trading Decision Log](postgres.md#trading-decision-log), which is also the order queue. Executors never size or place orders: the [risk-engine](risk-engine.md) approves and sizes each request through the [budget-allocator](budget-allocator.md), then the [execution-engine](execution-engine.md) places it. An executor can't bypass or override either.
- An exit closes the whole position, or a share of it (`close_fraction`, e.g. 0.5) — the rest stays open.
- An [averaging paper](papers.md#averaging-papers)'s position management (take-profit, give-up, averaging down) runs in the shared loop, ahead of the strategy, for every executor: the strategy only decides its entries; the open position is managed by the paper's parameters.
- A paper with an order in flight (`pending` / `approved`) gets no new signal until it's resolved. The same signal (enter / exit, direction, reason) is queued at most once per candle.
- Open no new positions while the risk engine blocks this executor or paper, the [watchdog](watchdog.md#kill-switch) kill switch is active, or the paper's `direction` doesn't allow it. Open positions keep being managed (exits still run).
- Place nothing for **live** papers — no entries, no exits — while the dashboard's [auto-trading switch](dashboard.md#live-cards) is off (it's off after every start): each signal is still logged to the decision log, as `rejected_by_risk` with reason "live auto-trading off" (once per signal per candle; turned on mid-candle, the candle's signal still goes through).

## Order Flow

```
executor ──pending──▶ risk-engine ──approved / rejected_by_risk──▶ execution-engine ──placed / failed
```

All three steps update the same `trading_decisions` row.

**Timing.** Candles close on minute boundaries. Market-data fetches every (asset, interval) concurrently at hh:mm:02, so the closed candle is stored within about a second; the feature engine checks every 5 s (:00, :05, …) and computes a reading once per closed candle; executors run 1 s later (:01, :06, …); the risk and execution engines poll every 5 s. A signal on a candle close becomes a position about 10–15 s after the close, and a stop-and-reverse (exit, then the opposite entry) completes within the same minute.

**Each signal is queued at most once per reading (closed candle).** If the risk engine rejects an entry, the executor doesn't queue it again until the next candle — this keeps the 5 s loop from flooding the log and tripping the watchdog's order-rate check.

## Implementation

`backend/app/executors/`: `base.py` (shared loop), one module per strategy, each run as its own container (`python -m app.executors.vwap`, `python -m app.executors.trend`, `python -m app.executors.supertrend`). Poll interval: `EXECUTOR_POLL_SECONDS` (default 5).

## Strategy Registry

The registry is the list of papers and their state (mode, enabled/disabled, profitability), stored in [postgres](postgres.md). A paper is disabled manually or by the risk engine; see [papers: Lifecycle](papers.md#lifecycle).

---
[← Back to README](../README.md)
