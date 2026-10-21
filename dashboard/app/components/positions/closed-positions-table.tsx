import {
  Table,
  TableBody,
  TableCell,
  TableHead,
  TableHeader,
  TableRow,
} from "@/components/ui/table";
import { LocalTime } from "@/components/local-time";
import { formatNumber, formatPrice, formatUsd, pnlClass } from "@/lib/format";
import type { ClosedPosition } from "@/types/portfolio";

import { DIRECTION_CLASS } from "./direction";
import { PnlPercent } from "./pnl-percent";

const COLUMNS = [
  "Type",
  "Asset",
  "Dir",
  "Size",
  "Entry Price",
  "Close Price",
  "Realized PnL",
  "Exit",
  "Closed",
];

export function ClosedPositionsTable({ positions }: { positions: ClosedPosition[] }) {
  return (
    <Table>
      <TableHeader>
        <TableRow>
          {COLUMNS.map((c) => (
            <TableHead key={c}>{c}</TableHead>
          ))}
        </TableRow>
      </TableHeader>
      <TableBody>
        {positions.map((p) => (
          <TableRow key={p.id}>
            <TableCell className="uppercase">{p.mode}</TableCell>
            <TableCell className="font-medium">{p.asset}</TableCell>
            <TableCell className={`uppercase ${DIRECTION_CLASS[p.direction] ?? ""}`}>
              {p.direction}
            </TableCell>
            <TableCell>{formatNumber(p.size)}</TableCell>
            <TableCell>{formatPrice(p.entry_price)}</TableCell>
            <TableCell>{formatPrice(p.close_price)}</TableCell>
            <TableCell className={pnlClass(p.realized_pnl_usd)}>
              {formatUsd(p.realized_pnl_usd)}
              <PnlPercent pnl={p.realized_pnl_usd} margin={p.margin_usd} />
            </TableCell>
            <TableCell className="text-xs text-muted-foreground">{p.exit_reason ?? "—"}</TableCell>
            <TableCell className="text-xs text-muted-foreground">
              <LocalTime value={p.closed_at} withDate />
            </TableCell>
          </TableRow>
        ))}
      </TableBody>
    </Table>
  );
}
