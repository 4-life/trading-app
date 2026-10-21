import { Card, CardContent, CardHeader, CardTitle } from "@/components/ui/card";
import type { Paper } from "@/types/paper";

import { BatchSweepDialog } from "./batch-sweep-dialog";
import { CreatePaperDialog } from "./create-paper-dialog";
import { usePaperFilter } from "./hooks/use-paper-filter";
import { filterPapers, knownFilter, PapersFilters } from "./papers-filters";
import { PapersTable } from "./papers-table";

// docs/dashboard.md#papers
export function PapersCard({ papers, assets }: { papers: Paper[] | null; assets: string[] }) {
  const [saved, change] = usePaperFilter();
  const filter = papers === null ? saved : knownFilter(papers, saved);
  const shown = papers === null ? [] : filterPapers(papers, filter);
  return (
    <Card>
      <CardHeader className="flex flex-row items-center justify-between">
        <CardTitle>Papers</CardTitle>
        <div className="flex gap-2">
          <BatchSweepDialog papers={papers ?? []} />
          <CreatePaperDialog assets={assets} />
        </div>
      </CardHeader>
      <CardContent className="space-y-4">
        {papers === null ? (
          <p className="text-sm text-muted-foreground">Unavailable</p>
        ) : papers.length === 0 ? (
          <p className="text-sm text-muted-foreground">No papers yet</p>
        ) : (
          <>
            <PapersFilters papers={papers} filter={filter} onChange={change} />
            {shown.length === 0 ? (
              <p className="text-sm text-muted-foreground">No papers match the filter</p>
            ) : (
              <PapersTable papers={shown} />
            )}
          </>
        )}
      </CardContent>
    </Card>
  );
}
