import { formatUsd } from "@/lib/format";
import type { Portfolio } from "@/types/portfolio";

export const APP_TITLE = "Trading App";

// "🟢 +$12.34 · Trading App" - total PnL of live, or of demo when live has
// no data. A tab title can't be colored, so the emoji carries the color.
export function pnlTitle(live: Portfolio | null, demo: Portfolio | null): string {
  const useLive = Boolean(live?.live_data && live.stats);
  const stats = useLive ? live?.stats : demo?.stats;
  if (!stats) return APP_TITLE;
  const pnl = Number(stats.total_pnl_usd);
  const icon = pnl > 0 ? "🟢" : pnl < 0 ? "🔴" : "⚪";
  const value = `${pnl > 0 ? "+" : ""}${formatUsd(pnl)}`;
  return `${icon} ${value}${useLive ? "" : " demo"} · ${APP_TITLE}`;
}
