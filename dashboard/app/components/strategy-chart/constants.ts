// The exit reason of a backtest position still open on the last candle (unrealized).
export const OPEN_AT_END = "open_at_end";
// An averaging backtest position's forced closes, marked on the chart: the
// liquidation and the give-ups (backend LIQUIDATION_EXIT, MAX_DRAWDOWN_EXIT,
// OUT_OF_MARGIN_EXIT).
export const FORCED_EXITS: readonly string[] = ["liquidation", "max_drawdown", "out_of_margin"];

// The overlays the viewer can show or hide, as [key, label]; the hidden ones
// are kept in this browser under HIDDEN_INDICATORS_KEY (hooks/use-hidden-indicators.ts).
export const INDICATORS = [
  ["swings", "Swings"],
  ["zones", "Liquidity zones"],
  ["vwap", "VWAP + EMA 9"],
  ["bands", "Trend bands"],
  ["supertrend", "Supertrend"],
  ["keltner", "Keltner signals"],
] as const;
export const HIDDEN_INDICATORS_KEY = "chart-hidden-indicators";
