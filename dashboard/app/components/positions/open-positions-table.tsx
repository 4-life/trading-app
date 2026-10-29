import { Table, TableBody, TableHead, TableHeader, TableRow } from "@/components/ui/table";
import type { OpenPosition } from "@/types/portfolio";

import { OpenPositionRow } from "./open-position-row";

const COLUMNS = [
  "Paper",
  "Type",
  "Asset",
  "Dir",
  "Size",
  "Entry Price",
  "Current Price",
  "Unrealized PnL",
  "Margin",
  "Exposure",
  "Exit",
  "",
];

export function OpenPositionsTable({ positions }: { positions: OpenPosition[] }) {
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
        {positions.map((p) => (
          <OpenPositionRow key={p.id} position={p} />
        ))}
      </TableBody>
    </Table>
  );
}
