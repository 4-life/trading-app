// API response shapes (backend/app/api). Pydantic serializes Decimal as a
// JSON string - parse with Number() before formatting.

import type { Paper } from "@/types/paper";
import type { Mode } from "@/types/portfolio";

// GET /papers/{id}/chart (docs/api.md).
export interface ChartCandle {
  time: string;
  open: string;
  high: string;
  low: string;
  close: string;
  // An averaging hedge paper's: the hedge asset's close (its short's price).
  hedge_close: string | null;
}

export type SwingKind = "HH" | "LL" | "HL" | "LH";

export interface ChartSwing {
  kind: SwingKind;
  price: number;
  time: string;
  confirmed_at: string;
}

export interface ChartFill {
  time: string;
  side: "buy" | "sell";
  size: string;
  price: string | null;
}

export interface ChartPosition {
  id: number;
  mode: Mode;
  direction: string;
  size: string;
  entry_price: string;
  close_price: string | null;
  initial_margin_usd: string;
  realized_pnl_usd: string | null;
  unrealized_pnl_usd: string | null;
  entry_reason: string | null;
  stop_loss_price: string | null;
  take_profit_price: string | null;
  exit_reason: string | null;
  opened_at: string;
  closed_at: string | null;
  fills: ChartFill[];
}

// Temporary simulated backtest trade (docs/vwap-strategy-engine.md#backtest).
export interface BacktestTrade {
  direction: string;
  opened_at: string;
  entry_price: string;
  stop_loss_price: string | null; // null: no stop-loss (VWAP)
  closed_at: string;
  close_price: string;
  entry_reason: string | null;
  exit_reason: string;
  return_pct: string;
  // An averaging paper's position: all the margin put in, the PnL net of fees,
  // and its buys (the first entry, then every add); null / empty otherwise.
  margin_usd: string | null;
  pnl_usd: string | null;
  // An averaging hedge position: its shorts' part of pnl_usd; null otherwise.
  hedge_pnl_usd: string | null;
  fills: BacktestFill[];
}

export interface BacktestFill {
  // a buy: the first entry or an add; a sell: a unit sold (a dip unit unwound,
  // or a signal unit while in loss and bearish); short_*: a hedge short's fill.
  side: "buy" | "sell" | `short_${string}`;
  time: string;
  price: string; // a short's: the hedge asset's
  margin_usd: string; // a sell or a short's reduce / close: the margin released
  notional_usd: string;
  // A sell: its unit's profit (before fees); a short's reduce / close: its PnL.
  realized_pnl_usd: string | null;
  // The position right after this fill (a short's: the long's, unchanged).
  total_margin_usd: number;
  avg_entry: number;
  leverage: number;
  liquidation_price: number;
  pnl_usd: number; // at this buy's price, before fees
}

// A confirmed LuxAlgo liquidity swing zone (every chart).
export interface LiquidityZone {
  kind: "low" | "high";
  start: string;
  end: string;
  top: number;
  btm: number;
  confirmed_at: string;
}

export interface VwapPoint {
  time: string;
  vwap: number | null; // null before the chart's first full session
  ema: number;
  signal: "long" | "short" | null; // BUY | SELL at this candle's close
}

// BigBeluga trend bands (every chart).
export interface BandPoint {
  time: string;
  state: 1 | -1 | 0; // bullish | bearish | before the first cross
  band: number | null; // lower band while bullish, upper while bearish
  inner: number | null; // 1 ATR inside the band: the value zone's edge
  signal: "long" | "short" | null; // break-up | break-down at this candle's close
}

// A Supertrend paper's Supertrend (docs/supertrend-strategy-engine.md).
export interface SupertrendPoint {
  time: string;
  line: number | null; // the up band in an uptrend, the dn band in a downtrend
  trend: 1 | -1 | null; // null: no trendline yet
  signal: "long" | "short" | null; // Buy | Sell at this candle's close
}

export interface PaperChart {
  paper_id: number;
  asset: string;
  timeframe: string;
  executor: string;
  kind: Paper["kind"];
  candles: ChartCandle[];
  swings: ChartSwing[];
  liquidity_zones: LiquidityZone[];
  vwap: VwapPoint[]; // VWAP + EMA 9 and their signals (every chart)
  bands: BandPoint[];
  supertrend: SupertrendPoint[]; // a Supertrend paper's only
  positions: ChartPosition[];
  backtest: BacktestTrade[];
}

// Older candles of a strategy chart, loaded as it scrolls back (GET /papers/{id}/candles),
// with the first window's overlays on them.
export interface CandleChunk {
  candles: ChartCandle[];
  vwap: VwapPoint[];
  bands: BandPoint[];
  supertrend: SupertrendPoint[];
  swings: ChartSwing[]; // pivoting in the chunk
  liquidity_zones: LiquidityZone[];
}
