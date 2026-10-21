# Execution Engine

Docker service: `execution-engine`

The only component that places orders. Receives orders from [strategy executors](strategy-executor.md) only after the [risk-engine](risk-engine.md) approves them.

## Liquidation

A position is force-closed (reason `liquidation`) once its remaining margin — margin + unrealized PnL — falls to `MAINTENANCE_MARGIN_PCT` (default **20%**) of its initial margin. The execution engine checks every open demo position at the start of each pass. It also writes a heartbeat to Redis every pass; if the heartbeat goes stale (`EXECUTION_HEARTBEAT_STALE_SECONDS`, default 30), the [risk-engine](risk-engine.md) runs the same liquidation in its place. Row locks make sure a position is closed once. Each liquidation is logged to the decision log (outcome `placed`) and alerted. Live positions are skipped while the dashboard's [auto-trading switch](dashboard.md#live-cards) is off.

## Order Queue

Every `EXECUTION_POLL_SECONDS` (default 5) it takes the `approved` requests from the order queue ([Trading Decision Log](postgres.md#trading-decision-log)), oldest first, and handles each in one database transaction:

- **filled** → `outcome = placed`, `order_id` set; an [averaging paper](papers.md#averaging-papers) whose take-profit closed its position is disabled in the same transaction;
- **can't be filled** (no size, insufficient balance, no open position to close, already open, live mode) → `outcome = failed`, the reason appended to `risk_reason`;
- **unexpected error** (e.g. Hyperliquid unreachable) → left `approved`, retried next pass.

`position_size_usd` set by the risk engine is the position's **notional** (exposure); the margin reserved is notional ÷ the paper's leverage — for an `add` ([averaging down](papers.md#averaging-papers)), ÷ its `add_leverage`.

Code: `backend/app/execution_engine/` — `engine.py` (queue loop), `demo.py` (fill math), `run.py` (entrypoint).

## Trading Venue

Primary execution platform: **Hyperliquid**.

- Use official API/WebSocket interfaces.
- Support spot/perpetual instruments depending on actual availability.
- Tokenized equities may only be traded when the specific instrument is available to the selected account/jurisdiction.

The architecture must not be tightly coupled to a single exchange. All venue access goes through an exchange abstraction:

```
ExchangeAdapter
    connect()
    get_balances()
    get_positions()
    get_open_orders()
    get_market_data()
    place_order()
    cancel_order()
    modify_order()
    get_order()
```

This allows another venue to be added later without touching strategy or risk logic.

## Demo Execution

Demo orders are filled in [postgres](postgres.md) at the selected provider's current market price (`get_market_data`; Hyperliquid without an exchange API), market orders only:

- **Spread**: a market order crosses the spread — buys fill at the best ask, sells at the best bid, read from the provider's order book at fill time (the same snapshot `get_market_data` returns; its mid is the market price). The [maintenance-margin check](#liquidation) uses the mid.
- **Fee**: the provider's taker fee, % of notional, on entry and on exit — Hyperliquid 0.045%, Lighter none (`TAKER_FEE_RATES` in `backend/app/system/exchange_api.py`). The risk engine's free-balance check and the exit-fee estimate for a position closed on the exchange use the same rate.
- **Entry**: reserves margin (notional ÷ leverage) + entry fee from the demo balance; creates the position and the order.
- **Exit**: charges the exit fee and the funding accrued while open (longs pay positive rates, shorts receive them); returns the reserved margin + price PnL − exit fee − funding to the demo balance; closes the position. `realized_pnl_usd` = price PnL − both fees − funding.
- **Add** (averaging down, [position management](papers.md#averaging-papers)): reserves the add's margin (notional ÷ `add_leverage`) + its fee from the demo balance and grows the open position: size + the add's, the average entry recomputed, margin + the add's, leverage = notional at entry ÷ margin. A buy order on the same position records it. Without an open position it fails.
- **Partial exit** (`close_fraction` < 1): closes that share of the size the same way — its share of the margin, funding and entry fee — and leaves the rest open with the reduced size and margin. `realized_pnl_usd` adds up over every close; profitability divides by `initial_margin_usd`, the margin reserved at open.

## Live Execution

Live requests go to the [exchange API](dashboard.md#exchange-api) selected in the settings — its provider, on mainnet (`backend/app/execution_engine/live.py`, `live_lighter.py`). The same provider supplies all [market data](market-data.md#providers), so signals and fills see the same prices.

- **Credentials** — without an exchange API, live requests fail and live cards show "no live data".
  - **Hyperliquid** — the **API (agent) wallet private key**, which can trade but not withdraw, and the **main account address** it trades for.
  - **Lighter** — an **API key private key** of the account, the **account index** and the **API key index** (orders signed by `lighter-sdk`'s bundled signer).
- **Mainnet only** — live means real money; test strategies in demo mode (real prices, simulated fills). A testnet API saved before testnet was dropped is ignored.
- **Entry** — size = notional ÷ the mid price, rounded down to the asset's size step; the paper's leverage is set as **isolated** margin on the asset, then a market order. Leverage must be a whole number.
- **Market orders** — capped at `LIVE_SLIPPAGE_PCT` (default **0.5%**) from the mid price (Hyperliquid: an IOC limit order; Lighter: the worst average price). If the price moves more, the order doesn't fill.
- **Refused orders** — an order the exchange refuses or doesn't fill (e.g. a coin the provider doesn't list) is `rejected_by_provider`, with the exchange's reason.
- **Recorded** — the real fill price, size, order id and fee in `orders` / `positions`; live profitability updates on every close. A Lighter market order's fill is read back from the account's trades (matched by the order's client index, up to 15 s); standard Lighter accounts pay no fees.
- **Add** (averaging down) — a market order on the same side grows the isolated position; it leaves the position's leverage setting (the paper's leverage) alone, so the order itself takes margin at that leverage. The rest of the add's margin (notional ÷ `add_leverage` minus what the order took) is then moved into the isolated position: Lighter `update_margin` (add collateral), Hyperliquid `updateIsolatedMargin`. If that transfer fails, the add stays recorded at the paper's leverage, and it's alerted.
- **Exit** — a market order on the opposite side, for the whole size or `close_fraction` of it (rounded down to the asset's size step). A partial close or partial fill reduces the position and leaves it open; the next exit signal closes the rest. Each close carries its share of the entry fees (the first entry's and every add's).
- **Funding** is settled by the exchange on the account, not included in a position's realized PnL.
- **Liquidation** — the [20% maintenance rule](#liquidation) applies to live positions too, priced from the exchange, before its own liquidation — only while live auto-trading is on.
- **Closed outside the app** — a live position closed on the exchange by hand (or liquidated there) is recorded with the dashboard's **Doesn't exist** action (`POST /positions/{id}/closed-on-exchange`), at the price the owner enters.
- **Balance** — the live total (budget allocator, risk limits, live cards) is the account value; free cash is the withdrawable (Lighter: available) amount.
- **Reconciliation** — the [watchdog](watchdog.md#monitoring)'s `live_reconciliation` check compares open live positions in the database with the account.

## Key Custody

The seed/private key of the main wallet is never stored on the VPS. Signing/custody is handled outside the VPS (e.g. hardware wallet, external signer, or a key-restricted API/agent wallet). The API key used by the app is trade-only — no withdrawal permission.

---
[← Back to README](../README.md)
