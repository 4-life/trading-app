// The exit reason of a backtest position still open on the last candle (unrealized).
export const OPEN_AT_END = "open_at_end";
// An averaging backtest position's forced closes, marked on the chart: the
// liquidation and the give-ups (backend LIQUIDATION_EXIT, MAX_DRAWDOWN_EXIT,
// OUT_OF_MARGIN_EXIT).
export const FORCED_EXITS: readonly string[] = ["liquidation", "max_drawdown", "out_of_margin"];

// A hedge short's fill: why it happened (backend app/backtest/hedge.py's SHORT_*).
export const SHORT_FILLS: Record<string, string> = {
  short_open: "short opened: bearish, the long in loss",
  short_add: "short added to: the long added",
  short_margin: "short margin topped up: half its margin lost, bearish, the pair in loss",
  short_reduce: "short reduced: the long's loss shrank",
  short_covered: "short closed: the pair's PnL covered",
  short_half_covered: "short closed: big margins, half the long's loss covered",
  short_out_of_margin: "short gave up: out of margin",
  short_with_long: "short closed with the long",
};

// The overlays the viewer can show or hide, as [key, label]; the hidden ones
// are kept in this browser under HIDDEN_INDICATORS_KEY (hooks/use-hidden-indicators.ts).
export const INDICATORS = [
  ["swings", "Swings"],
  ["zones", "Liquidity zones"],
  ["vwap", "VWAP + EMA 9"],
  ["bands", "Trend bands"],
  ["supertrend", "Supertrend"],
] as const;
export const HIDDEN_INDICATORS_KEY = "chart-hidden-indicators";
