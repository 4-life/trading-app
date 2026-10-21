import { pnlPercent } from "@/lib/format";

// "(+1.24%)" next to a PnL amount; nothing when it can't be computed.
export function PnlPercent({ pnl, margin }: { pnl: string | null; margin: string }) {
  const pct = pnlPercent(pnl, margin);
  return pct ? <span className="ml-1 text-xs">({pct})</span> : null;
}
