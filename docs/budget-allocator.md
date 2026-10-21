# Budget Allocator

A shared library module, **not** a separate service. Used by the [risk-engine](risk-engine.md) to size approved entries and to check budgets.

## Responsibilities

- Read the available balance for a mode:
  - **demo** — the demo cash plus the margin reserved in open demo positions, from the database; $5000 at start and after a [reset](papers.md#demo-reset);
  - **live** — the exchange account value ([exchange API](dashboard.md#exchange-api)). Without an exchange API, there is no live budget and the dashboard shows "no live data" (not an error).
- Split each mode's balance **per paper** — every paper trades only within its own budget:

  ```
  paper_budget = (total − total × 0.1) / papers.length
  ```

  `total` is the mode's balance (demo or live); `papers.length` is the number of **enabled** papers in that mode. 10% of the balance is always kept free (`BUDGET_RESERVE_PCT`).
- The budget is the paper's **margin**; the position's notional is budget × the paper's leverage. The [risk limits](risk-engine.md#limits) cap the margin too, so leverage scales the position.
- Give each position its size from the paper's budget, leverage, asset and fees.
- Keep demo and live budgets fully separate — demo spending never affects the live budget and vice versa.

See [papers](papers.md#modes).

---
[← Back to README](../README.md)
