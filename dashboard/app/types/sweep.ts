// API response shapes (backend/app/api). Pydantic serializes Decimal as a
// JSON string - parse with Number() before formatting.

// A paper's settings sweep (its latest) - GET /papers/{id}/sweep (docs/api.md).
export interface PaperSweep {
  id: number;
  paper_id: number;
  status: "running" | "done" | "failed" | "stopped";
  max_leverage: string;
  max_margin: string | null; // an averaging paper's
  start: string | null; // the period its runs trade over; null until loaded
  split: string | null; // train before it, test after
  end: string | null;
  runs_total: number; // 0 until the candles are loaded
  runs_done: number;
  error: string | null;
  started_at: string;
  finished_at: string | null;
}

// One run of a sweep: its settings and stats (GET /papers/{id}/sweep/runs).
export interface SweepRun {
  leverage: number;
  add_leverage: number;
  initial_size_usd: number;
  add_size_usd: number;
  take_profit_pct: number; // of the margin, a fraction
  intraday: boolean;
  reopen: boolean; // intraday, reopened after a take-profit while the trend lasts
  compound: boolean; // the budget grows with the realized PnL
  total_usd: number; // closed + the position still open at the end
  closed_pnl_usd: number;
  open_unrealized_usd: number;
  train_pnl_usd: number;
  test_pnl_usd: number;
  positions: number;
  won: number;
  give_ups: number;
  liquidations: number;
  most_margin_usd: number;
  cash_drawdown_usd: number;
}

// One run of a single paper's sweep (GET /papers/{id}/sweep/exit-runs): its
// leverage, stop-loss and take-profit (shares of price; null: none) and its
// strategy's trades compounded at that leverage (% of the margin).
export interface ExitSweepRun {
  leverage: number;
  stop_loss_pct: number | null;
  take_profit_pct: number | null;
  return_pct: number;
  max_drawdown_pct: number;
  train_return_pct: number;
  test_return_pct: number;
  trades: number;
  won: number;
  stops: number;
  take_profits: number;
  liquidations: number;
}

// /sweep-status: the paper's sweep (null: none yet) and its best runs so far
// (a single paper's: ExitSweepRun; an averaging paper's `runs` on a fixed
// budget, `compound_runs` compounding), and the sweep running on the server,
// any paper's (GET /sweeps/running).
export interface SweepStatus {
  sweep: PaperSweep | null;
  runs: SweepRun[] | ExitSweepRun[];
  compound_runs: SweepRun[];
  running: PaperSweep | null;
}

// Several averaging papers' sweeps run one after another, each on the same
// budget - the latest batch (GET /sweeps/batch).
export interface SweepBatch {
  id: number;
  status: "running" | "done" | "failed" | "stopped";
  max_margin: string;
  paper_ids: number[];
  current_paper_id: number | null;
  papers_done: number;
  error: string | null;
  started_at: string;
  finished_at: string | null;
  current: PaperSweep | null; // the running paper's sweep
}
