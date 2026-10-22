import type { ReactNode } from "react";

import { Card, CardContent, CardHeader, CardTitle } from "@/components/ui/card";
import type { Portfolio } from "@/types/portfolio";

import { StatsGrid } from "./stats-grid";

// One mode's cards (docs/dashboard.md#live-cards / #demo-cards).
export function StatsCard({
  title,
  portfolio,
  accent,
  action,
  compact = false,
}: {
  title: string;
  portfolio: Portfolio | null;
  accent: string;
  action?: ReactNode;
  compact?: boolean; // smaller cards (demo)
}) {
  const stats = portfolio?.stats ?? null;
  return (
    <Card size={compact ? "sm" : "default"} className={`border-l-4 ${accent} ${compact ? "" : "bg-muted/5"}`}>
      <CardHeader className="flex flex-row flex-wrap items-center justify-between gap-2">
        <CardTitle>{title}</CardTitle>
        {action}
      </CardHeader>
      <CardContent>
        {portfolio === null ? (
          <p className="text-sm text-muted-foreground">Unavailable</p>
        ) : !portfolio.live_data || stats === null ? (
          <p className="text-sm text-muted-foreground">no live data</p>
        ) : (
          <StatsGrid stats={stats} compact={compact} />
        )}
      </CardContent>
    </Card>
  );
}
