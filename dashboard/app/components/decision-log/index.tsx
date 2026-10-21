import { Card, CardContent, CardHeader, CardTitle } from "@/components/ui/card";
import type { DecisionPage } from "@/types/decision";

import { DecisionsTable } from "./decisions-table";
import { DecisionLogFilters } from "./filters";
import { DecisionLogPagination } from "./pagination";

// The trading log (docs/dashboard.md#trading-log).
export function DecisionLogCard({ page, assets }: { page: DecisionPage | null; assets: string[] }) {
  return (
    <Card>
      <CardHeader className="flex flex-row flex-wrap items-center justify-between gap-2">
        <CardTitle>Trading Log{page ? ` (${page.total})` : ""}</CardTitle>
        <DecisionLogFilters assets={assets} />
      </CardHeader>
      <CardContent className="space-y-3">
        {page === null ? (
          <p className="text-sm text-muted-foreground">Unavailable</p>
        ) : page.items.length === 0 ? (
          <p className="text-sm text-muted-foreground">No decisions</p>
        ) : (
          <DecisionsTable decisions={page.items} />
        )}
        {page && (
          <DecisionLogPagination page={page.page} pageSize={page.page_size} total={page.total} />
        )}
      </CardContent>
    </Card>
  );
}
