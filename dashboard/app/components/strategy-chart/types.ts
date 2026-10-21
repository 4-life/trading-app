import type { INDICATORS } from "./constants";

// An averaging backtest position at a candle's close (`close`; `hedgeClose`:
// the hedge asset's), from its fills up to that candle (`until`, exclusive -
// the candle's end): the long's average entry, margin and PnL (its sales'
// plus the size held, before fees) and its short's margin and PnL (its
// reduces' and closes' plus the size held). Replays the backend's
// Position.buy / sell (app/backtest/averaging.py) and Short (app/backtest/hedge.py).
export interface PositionState {
  avgEntry: number;
  margin: number;
  pnl: number;
  shortMargin: number;
  shortPnl: number | null; // null: no hedge asset price at the candle
}

// One of the overlays the viewer can show or hide.
export type Indicator = (typeof INDICATORS)[number][0];
