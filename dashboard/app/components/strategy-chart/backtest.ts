import type { BacktestTrade } from "@/types/chart";

import type { PositionState } from "./types";

// The size an averaging backtest position held at its end: bought minus sold.
function heldSize(t: BacktestTrade): number {
  return t.fills.reduce(
    (a, f) => a + ((f.side === "sell" ? -1 : 1) * Number(f.notional_usd)) / Number(f.price),
    0,
  );
}

// An averaging backtest position's value in USD: the size it held at its end, at
// its average entry and at the close (or the last price, still open).
export function positionValue(t: BacktestTrade): { entry: number; close: number } {
  const size = heldSize(t);
  return { entry: size * Number(t.entry_price), close: size * Number(t.close_price) };
}

// stateAt: see PositionState (./types).
export function stateAt(t: BacktestTrade, until: number, close: number): PositionState {
  let size = 0;
  let cost = 0;
  let margin = 0;
  let realized = 0;
  // A short position: the PnL mirrored.
  const sign = t.direction === "short" ? -1 : 1;
  for (const f of t.fills) {
    if (new Date(f.time).getTime() / 1000 >= until) {
      break;
    }
    const price = Number(f.price);
    const notional = Number(f.notional_usd);
    const fillMargin = Number(f.margin_usd);
    if (f.side === "sell") {
      const sold = notional / price;
      realized += sign * sold * (price - cost / size);
      cost -= cost * (sold / size);
      size -= sold;
      margin -= fillMargin;
    } else {
      size += notional / price;
      cost += notional;
      margin += fillMargin;
    }
  }
  const avgEntry = size > 0 ? cost / size : 0;
  return { avgEntry, margin, pnl: realized + sign * size * (close - avgEntry) };
}

// An averaging backtest position's adds: its buys after the first entry.
export const addCount = (t: BacktestTrade) =>
  Math.max(t.fills.filter((f) => f.side === "buy").length - 1, 0);

// An averaging backtest position's sales: dip units unwound, signal units sold.
export const sellCount = (t: BacktestTrade) => t.fills.filter((f) => f.side === "sell").length;

// Per fill, a sell's own profit: its unit's size x (sell price - that unit's buy
// price), as the backtest stored it. A backtest run before that was stored: the
// unit sold is the lowest dip unit held but the lowest (kept to the close).
// The exchange books it against the average entry instead, so a unit sold under
// it reads as a loss there. 0 for a buy.
export function unitProfits(t: BacktestTrade): number[] {
  const first = Number(t.fills[0]?.price ?? 0);
  const lots: number[] = []; // dip units' buy prices
  return t.fills.map((f, k) => {
    const price = Number(f.price);
    if (f.side === "sell" && f.realized_pnl_usd !== null) {
      return Number(f.realized_pnl_usd);
    }
    if (f.side === "buy") {
      if (k > 0 && price < first) {
        lots.push(price);
      }
      return 0;
    }
    if (lots.length < 2) {
      return 0;
    }
    const sold = [...lots].sort((a, b) => a - b)[1];
    lots.splice(lots.indexOf(sold), 1);
    return (Number(f.notional_usd) / price) * (price - sold);
  });
}
