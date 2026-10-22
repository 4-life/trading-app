export const TIMEFRAMES = ['1m', '5m', '15m', '1h', '4h'] as const;
// Executors a scanner paper can run (the API's _SCANNER_EXECUTORS).
export const SCANNER_EXECUTORS = ['trend'] as const;
export const EXECUTORS: Record<string, readonly string[]> = {
  trend: ['long', 'short', 'both'],
  vwap: ['long', 'both'],
  supertrend: ['long', 'short'],
  regime: ['long', 'short', 'both'],
};

// The stats the runs can be sorted by (the API's `sort`), as [key, label].
export const SWEEP_SORTS = [
  ["total_usd", "Total PnL"],
  // The fewest give-ups (liquidations too), the best total PnL among them.
  ["safest_total", "PnL + give-ups"],
  ["test_pnl_usd", "Test PnL"],
  ["train_pnl_usd", "Train PnL"],
  ["closed_pnl_usd", "Closed PnL"],
  ["won", "Won"],
  ["give_ups", "Give-ups"],
  ["most_margin_usd", "Most margin"],
  ["cash_drawdown_usd", "Cash drawdown"],
] as const;

export const EXIT_SWEEP_SORTS = [
  ["return_pct", "Return"],
  ["test_return_pct", "Test return"],
  ["train_return_pct", "Train return"],
  ["max_drawdown_pct", "Max drawdown"],
  ["won", "Won"],
  ["liquidations", "Liquidations"],
] as const;

// "Find best params" (edit-paper-modal/sweep-panel.tsx): the inputs' defaults, the poll while a
// sweep runs, and the stats lower is better for (higher for the rest).
export const SWEEP_DEFAULT_MAX_LEVERAGE = 100;
export const SWEEP_DEFAULT_MAX_MARGIN = 1000;
export const SWEEP_POLL_MS = 5000;
export const SWEEP_ASCENDING: readonly string[] = ["give_ups", "most_margin_usd", "liquidations"];

// The papers table's filter (hooks/use-paper-filter.ts): none, and this browser's key.
export const NO_FILTER = { kind: "", executor: "", asset: "", enabledOnly: false, liveOnly: false } as const;
export const PAPER_FILTER_KEY = "papers-filter";
