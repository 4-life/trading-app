// Where an averaging paper's automatic give-up lands (docs/papers.md#averaging-papers),
// from its settings alone - the dip add ladder of app/backtest/averaging.py (signal
// adds and unwinds left out). Keep the shares in step with
// app/executors/position_management.py and the maintenance margin with the backend's.
const ADD_AT_MARGIN_LEFT = 0.5;
const GIVE_UP_AT_MARGIN_LEFT = 0.3;
const MAINTENANCE = 0.2;
const MAX_ADDS = 100_000;

export interface GiveUp {
  // The move against the first entry, a fraction (a long's drop, a short's
  // rise): where it closes (out_of_margin).
  drop: number;
  liquidation: number; // the move the exchange would liquidate at, just past it
  adds: number; // dip adds before the max margin stops them
  margin: number; // locked by then
}

// The (add, give-up) shares of the margin left - margin_levels in
// app/executors/position_management.py: the exchange's `maintenance` margin
// (of the notional) liquidating before MAINTENANCE moves them up with it.
function levels(margin: number, cost: number, maintenance: number | null): [number, number] {
  const liquidation =
    maintenance === null ? MAINTENANCE : Math.min(Math.max(MAINTENANCE, (maintenance * cost) / margin), 1);
  const scale = (1 - liquidation) / (1 - MAINTENANCE);
  return [
    liquidation + (ADD_AT_MARGIN_LEFT - MAINTENANCE) * scale,
    liquidation + (GIVE_UP_AT_MARGIN_LEFT - MAINTENANCE) * scale,
  ];
}

// The first buy at 1: each dip add at the price where the margin left falls to
// the add level, until the next would pass `maxMargin`; then the give-up at
// its level (both from levels(), with the asset's `maintenance` margin, null:
// not known). Null without a max margin (adds until the cash runs out) or
// with a setting missing. `short`: a short paper's - mirrored, the price rising.
export function giveUp(
  leverage: number,
  initial: number,
  addSize: number,
  addLeverage: number,
  maxMargin: number,
  maintenance: number | null = null,
  short = false,
): GiveUp | null {
  const settings = [leverage, initial, addSize, addLeverage, maxMargin];
  if (!settings.every((x) => x > 0)) {
    return null;
  }
  let size = initial * leverage;
  let cost = size;
  let margin = initial;
  let adds = 0;
  const sign = short ? -1 : 1;
  const at = (left: number) => (cost - sign * margin * (1 - left)) / size;
  // How far against the first entry `price` is - a long can't drop past 100%.
  const against = (price: number) => (short ? price - 1 : Math.min(1 - price, 1));
  while (margin + addSize <= maxMargin && adds < MAX_ADDS) {
    const level = at(levels(margin, cost, maintenance)[0]);
    if (level <= 0) {
      break;
    }
    size += (addSize * addLeverage) / level;
    cost += addSize * addLeverage;
    margin += addSize;
    adds += 1;
  }
  // The exchange's liquidation: the equity down to its maintenance x the notional.
  const liquidation =
    maintenance === null
      ? at(MAINTENANCE)
      : (cost - sign * margin) / (size * (1 - sign * maintenance));
  return {
    drop: against(at(levels(margin, cost, maintenance)[1])),
    liquidation: against(liquidation),
    adds,
    margin,
  };
}
