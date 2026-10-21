import { formatUsd, pnlClass } from "@/lib/format";
import type { Stats } from "@/types/portfolio";

import { StatCard } from "./stat-card";

// Equity, Available Balance, Open Positions, Exposure, Total / Unrealized /
// Realized PnL (docs/dashboard.md#live-cards).
export function StatsGrid({ stats }: { stats: Stats }) {
  return (
    <div className="grid grid-cols-2 gap-3 sm:grid-cols-4 lg:grid-cols-7">
      <StatCard label="Equity" value={formatUsd(stats.equity_usd)} />
      <StatCard label="Available Balance" value={formatUsd(stats.available_balance_usd)} />
      <StatCard label="Open Positions" value={String(stats.open_positions)} />
      <StatCard label="Exposure" value={formatUsd(stats.exposure_usd)} />
      <StatCard
        label="Total PnL"
        value={formatUsd(stats.total_pnl_usd)}
        tone={pnlClass(stats.total_pnl_usd)}
      />
      <StatCard
        label="Unrealized PnL"
        value={formatUsd(stats.unrealized_pnl_usd)}
        tone={pnlClass(stats.unrealized_pnl_usd)}
      />
      <StatCard
        label="Realized PnL"
        value={formatUsd(stats.realized_pnl_usd)}
        tone={pnlClass(stats.realized_pnl_usd)}
      />
    </div>
  );
}
