// API response shapes (backend/app/api). Pydantic serializes Decimal as a
// JSON string - parse with Number() before formatting.

import type { Mode } from "@/types/portfolio";

export interface Paper {
  id: number;
  asset: string;
  timeframe: string;
  leverage: string;
  direction: string;
  mode: Mode;
  executor: string;
  // 'scanner': no asset of its own - creates single papers (docs/papers.md#kinds).
  // 'averaging': a single paper with position management (docs/papers.md#averaging-papers).
  // 'averaging_hedge': averaging fuelled by an ETH short - backtest only
  // (docs/papers.md#averaging-hedge-papers).
  kind: "single" | "scanner" | "averaging" | "averaging_hedge";
  parent_id: number | null;
  // backfilling / backtesting / failed; null = ready (docs/papers.md#preparation).
  prep_status: "backfilling" | "backtesting" | "failed" | null;
  prep_error: string | null;
  profitability_demo: string;
  profitability_live: string;
  backtest_return_pct: string | null; // net % of price after fees; null = no backtest
  backtest_net_usd: string | null; // an averaging paper's net PnL after fees; null otherwise
  enabled: boolean;
  enabled_at: string;
  disabled_by: string | null;
  disabled_reason: string | null;
  blocked_reason: string | null;
  max_leverage: string | null; // the asset's at the selected provider; null: not known yet
  // An averaging paper's position management (docs/papers.md#averaging-papers);
  // null for the other kinds. Shares are fractions ("0.3" = 30%).
  initial_size_usd: string | null;
  add_leverage: string | null;
  add_size_usd: string | null;
  max_drawdown_pct: string | null;
  take_profit_pct: string | null;
  backtest_start: string | null; // where its backtest starts; null = the whole history
  max_margin_usd: string | null; // the most margin a position may lock; null = no cap
  intraday: boolean; // close at the take-profit at once and keep running
  // The asset's maintenance margin at the exchange, a share of the notional;
  // null: not known yet.
  maintenance_margin: string | null;
  compound_margin: boolean; // the max margin grows with the realized PnL
  // Intraday: a fresh position after a take-profit while the strategy's trend lasts.
  reopen_in_trend: boolean;
  // A single paper's own exits, fractions of the entry price; null: none
  // (docs/papers.md#stop-loss-and-take-profit).
  stop_loss_pct: string | null;
  price_take_profit_pct: string | null;
  created_at: string;
  updated_at: string;
}
