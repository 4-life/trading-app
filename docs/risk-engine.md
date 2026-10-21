# Risk Engine

Docker service: `risk-engine`

Sits above every other container and checks risk and budget in real time. No [strategy executor](strategy-executor.md) can override or bypass it.

## Responsibilities

Every `RISK_POLL_SECONDS` (default 5):

1. **Decide every order.** Takes `pending` requests from the order queue ([Trading Decision Log](postgres.md#trading-decision-log)):
   - exits are always approved — closing only reduces risk;
   - entries are rejected if the paper is disabled or blocked, the kill switch is active, **another paper already holds the asset in that mode** (an open position, or an approved entry waiting to fill — an exchange account has one net position per coin, so demo follows live), or the mode has no balance data (live, for now). Otherwise the [budget-allocator](budget-allocator.md) gives the paper's margin budget — or the paper's fixed `initial_size_usd` ([position management](papers.md#averaging-papers)) — notional = margin × leverage, capped by the [limits](#limits), and it must fit the free cash.
   - **averaging papers** ([averaging papers](papers.md#averaging-papers)) are held to their own limits — their max margin and max drawdown — instead: their entries skip the risk blocks, the drawdown and daily-loss limits and the position / exposure limits (the first entry is its fixed `initial_size_usd`, if the free cash covers it), and they're never disabled by the loss limit below. Still rejected while disabled, under the watchdog kill switch, or with the asset held by another paper.
   - **adds** (averaging down) are rejected if the paper is disabled, the watchdog kill switch is active, averaging down is off for it, the add would take the position past its `max_margin_usd`, or the free cash doesn't cover the add's margin and fee — never by a risk block: the open position must be able to defend itself. Notional = `add_size_usd` (or `initial_size_usd`) × `add_leverage`, **not** resized by the limits: an add is what keeps the position from a margin call, so it's all or nothing. Approved → `approved` with `position_size_usd` (notional); rejected → `rejected_by_risk` with the reason, plus a risk event.
2. **Record equity** per mode once a minute (`equity_snapshots`) — the drawdown and daily-loss limits read it. The drawdown kill switch's peak is the highest equity recorded, so **adding or deleting the exchange API clears the live history** (`backend/app/system/exchange_api.py`): a new, smaller account would otherwise read as a deep drawdown against the old one's balance and block every live entry for good.
3. **Disable losing papers.** When a paper's realized loss in its mode — counted from when it was created or last re-enabled (`enabled_at`) — reaches its **loss limit** of its budget: it's blocked from new entries at once (Redis `risk:block:paper:<id>`), and disabled (`disabled_by = risk_engine`) as soon as it has no open position or order in flight. Recorded as a risk event and alerted, with the limit and where it came from.
   - **Loss limit** — `PAPER_LOSS_DISABLE_PCT` (default **10%**), or for a paper with a backtest ([VWAP](vwap-strategy-engine.md#backtest)) its **backtest max drawdown × `PAPER_LOSS_BACKTEST_MULTIPLE`** (default **1.25**) when that's more, at most 100%. The drawdown is the one the [chart's summary](dashboard.md#strategy-chart) shows: compounded trade by trade at the paper's leverage. A strategy that wins rarely but big (~14% winners, −38% backtest drawdown at 3× → a ~47.5% limit) isn't stopped inside its normal losing streaks; one losing clearly more than its history still is.
4. **Liquidation fallback** — if the [execution-engine](execution-engine.md#liquidation)'s heartbeat is stale, liquidates positions below the maintenance margin in its place.

Blocks live in [Redis](redis.md) (`risk:block:executor:<name>`, `risk:block:paper:<id>`); disabled papers in [postgres](postgres.md). Re-enabling a paper clears its block.

The limit checks (`evaluate()`) are pure functions: positions, equity and PnL are passed in, so they're testable without a database or exchange.

Code: `backend/app/risk_engine/` — `service.py` (loop), `engine.py` / `limits.py` / `drawdown.py` (limits), `blocks.py`, `run.py`.

## Limits

Explicit, overridable settings:

| Setting | Default |
|---|---|
| `max_position_pct` | 20% of capital per position — on its **margin** (notional ÷ leverage) |
| `max_correlated_exposure_pct` | 50% of capital across a correlated group (`correlated_asset_groups`, none by default) — on net **margin** |
| `daily_loss_limit_pct` | 5% |
| `kill_switch_drawdown_pct` | 15% from peak equity |

Enforces:
- position limits
- correlated-exposure limits — correlated assets (e.g. several tokenized equities, or BTC + ETH) are not treated as independent risk exposures; groups are configured via `correlated_asset_groups`
- drawdown limits
- kill-switch conditions
- budget — a paper never exceeds its own budget

Limits are per mode: `capital` and equity mean the demo total or the live total, evaluated separately.

## Long/Short Risk Semantics

Position side is an explicit input, not inferred — LONG and SHORT are distinct directions throughout exposure, PnL, stop-loss, and drawdown math:

- **PnL direction**: LONG loses when price falls, SHORT loses when price rises.
- **Position sizing is direction-independent**: `risk_amount = capital × risk_per_trade`; size comes from stop distance, not from which side the stop is on.
- **Worst-case margin loss** is bounded by `stop_loss_pct × leverage`, same for long and short.
- **Limits are on margin**, so leverage scales the position: with $5000 capital a position's margin is capped at $1000 — a $1000 notional at 1×, $10,000 at 10×. Profit and loss in dollars grow with leverage, and so does the risk (a 1% move on a 10× position = 10% of its margin).
- **Exposure/correlation limits net directions**: `max_correlated_exposure_pct` nets LONG against SHORT margin within a correlated group instead of summing it. The largest addable margin is `max_group_margin − sign × existing_net` (× the order's leverage = notional), which also handles an order that flips net exposure from one side of zero to the other.

---
[← Back to README](../README.md)
