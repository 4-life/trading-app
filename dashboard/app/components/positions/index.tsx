import { useState } from "react";

import { Card, CardContent, CardHeader, CardTitle } from "@/components/ui/card";
import { formatUsd } from "@/lib/format";
import type { ClosedPosition, Mode, OpenPosition } from "@/types/portfolio";

import { ClosedPositionsTable } from "./closed-positions-table";
import { type ModeFilter, PositionFilters, type PositionState } from "./filters";
import { OpenPositionsTable } from "./open-positions-table";

// docs/dashboard.md#positions-table
export function PositionsCard({ open, closed }: { open: OpenPosition[]; closed: ClosedPosition[] }) {
  const [state, setState] = useState<PositionState>("open");
  const [mode, setMode] = useState<ModeFilter>("all");
  const byMode = <T extends { mode: Mode }>(rows: T[]) =>
    mode === "all" ? rows : rows.filter((r) => r.mode === mode);
  const openRows = byMode(open);
  const closedRows = byMode(closed);
  const count = state === "open" ? openRows.length : closedRows.length;
  // All the margin the open positions shown lock together.
  const openMargin = openRows.reduce((sum, p) => sum + Number(p.margin_usd), 0);

  return (
    <Card>
      <CardHeader className="flex flex-row flex-wrap items-center justify-between gap-2">
        <CardTitle>
          {state === "open" ? "Open" : "Closed"} Positions ({count})
          {state === "open" && count > 0 && (
            <span className="ml-2 text-sm font-normal text-muted-foreground">
              margin {formatUsd(openMargin)}
            </span>
          )}
        </CardTitle>
        <PositionFilters state={state} mode={mode} onState={setState} onMode={setMode} />
      </CardHeader>
      <CardContent>
        {count === 0 ? (
          <p className="text-sm text-muted-foreground">No {state} positions</p>
        ) : state === "open" ? (
          <OpenPositionsTable positions={openRows} />
        ) : (
          <ClosedPositionsTable positions={closedRows} />
        )}
      </CardContent>
    </Card>
  );
}
