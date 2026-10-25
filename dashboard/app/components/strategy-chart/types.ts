import type { INDICATORS } from "./constants";

// An averaging backtest position at a candle's close (`close`), from its fills
// up to that candle (`until`, exclusive - the candle's end): its average entry,
// margin and PnL (its sales' plus the size held, before fees). Replays the
// backend's Position.buy / sell (app/backtest/averaging.py).
export interface PositionState {
  avgEntry: number;
  margin: number;
  pnl: number;
}

// One of the overlays the viewer can show or hide.
export type Indicator = (typeof INDICATORS)[number][0];
