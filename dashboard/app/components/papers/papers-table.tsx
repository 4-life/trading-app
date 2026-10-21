import { Table, TableBody, TableHead, TableHeader, TableRow } from "@/components/ui/table";
import type { Paper } from "@/types/paper";

import { PaperRow } from "./paper-row";

const COLUMNS = ["#", "Type / Executor", "Asset", "TF", "Dir", "Lev", "Mode", "Demo", "Live", "Backtest", "Status", ""];

export function PapersTable({ papers }: { papers: Paper[] }) {
  return (
    <Table>
      <TableHeader>
        <TableRow>
          {COLUMNS.map((c, i) => (
            <TableHead key={i}>{c}</TableHead>
          ))}
        </TableRow>
      </TableHeader>
      <TableBody>
        {papers.map((p) => (
          <PaperRow key={p.id} paper={p} />
        ))}
      </TableBody>
    </Table>
  );
}
