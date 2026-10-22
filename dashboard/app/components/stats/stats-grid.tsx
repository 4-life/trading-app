import { formatUsd, pnlClass } from "@/lib/format";
import type { Stats } from "@/types/portfolio";

import { StatCard } from "./stat-card";

// Equity, Available Balance, Open Positions, Exposure, Total / Unrealized /
// Realized PnL (docs/dashboard.md#live-cards).
export function StatsGrid({ stats, compact = false }: { stats: Stats; compact?: boolean }) {
  return (
    // Compact (demo): more tiles per row - a shorter card.
    <div
      className={`grid lg:grid-cols-7 ${compact ? "grid-cols-3 gap-1.5 sm:grid-cols-4" : "grid-cols-2 gap-3 sm:grid-cols-4"}`}
    >
      <StatCard compact={compact} label="Equity" value={formatUsd(stats.equity_usd)} />
      <StatCard compact={compact} label="Available Balance" value={formatUsd(stats.available_balance_usd)} />
      <StatCard compact={compact} label="Open Positions" value={String(stats.open_positions)} />
      <StatCard compact={compact} label="Exposure" value={formatUsd(stats.exposure_usd)} />
      <StatCard
        compact={compact}
        label="Total PnL"
        value={formatUsd(stats.total_pnl_usd)}
        tone={pnlClass(stats.total_pnl_usd)}
      />
      <StatCard
        compact={compact}
        label="Unrealized PnL"
        value={formatUsd(stats.unrealized_pnl_usd)}
        tone={pnlClass(stats.unrealized_pnl_usd)}
      />
      <StatCard
        compact={compact}
        label="Realized PnL"
        value={formatUsd(stats.realized_pnl_usd)}
        tone={pnlClass(stats.realized_pnl_usd)}
      />
    </div>
  );
}
