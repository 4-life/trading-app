import {
  Table,
  TableBody,
  TableCell,
  TableHead,
  TableHeader,
  TableRow,
} from "@/components/ui/table";
import { LocalTime } from "@/components/local-time";
import { PnlPercent } from "@/components/positions/pnl-percent";
import { formatNumber, formatPrice, formatUsd, pnlClass } from "@/lib/format";
import type { Decision } from "@/types/decision";

const COLUMNS = ["Time", "Type", "Asset", "Candidate", "Signal", "Outcome", "Size", "Price", "PnL", "Reason"];

const OUTCOME_CLASS: Record<string, string> = {
  placed: "text-green-500",
  rejected_by_risk: "text-red-500",
  failed: "text-red-500",
  rejected_by_provider: "text-red-500",
  pending: "text-amber-400",
  approved: "text-amber-400",
};

// An exit's result: the position's whole PnL on the order that closed it; a
// partial close's own PnL isn't stored.
function ExitPnl({ decision: d }: { decision: Decision }) {
  if (d.closed_position) {
    return (
      <TableCell className={pnlClass(d.realized_pnl_usd)}>
        {formatUsd(d.realized_pnl_usd)}
        {d.margin_usd && <PnlPercent pnl={d.realized_pnl_usd} margin={d.margin_usd} />}
      </TableCell>
    );
  }
  const partial = d.signal === "exit" && d.fill_price !== null;
  return <TableCell className="text-xs text-muted-foreground">{partial ? "partial" : "—"}</TableCell>;
}

// Coins filled (and their notional), else the size the decision asked for.
function Size({ decision: d }: { decision: Decision }) {
  if (d.fill_size === null || d.fill_price === null) {
    return <TableCell>{formatUsd(d.position_size_usd)}</TableCell>;
  }
  return (
    <TableCell>
      {formatNumber(d.fill_size, 4)}
      <div className="text-xs text-muted-foreground">
        {formatUsd(Number(d.fill_size) * Number(d.fill_price))}
        {d.fee_usd !== null && Number(d.fee_usd) > 0 ? ` · fee ${formatUsd(d.fee_usd)}` : ""}
      </div>
    </TableCell>
  );
}

// The fill price; an exit's position entry under it.
function Price({ decision: d }: { decision: Decision }) {
  return (
    <TableCell>
      {formatPrice(d.fill_price ?? d.entry_price)}
      {d.position_entry_price !== null && (
        <div className="text-xs text-muted-foreground">entry {formatPrice(d.position_entry_price)}</div>
      )}
    </TableCell>
  );
}

export function DecisionsTable({ decisions }: { decisions: Decision[] }) {
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
        {decisions.map((d) => (
          <TableRow key={d.id}>
            <TableCell className="text-xs text-muted-foreground"><LocalTime value={d.decided_at} withDate /></TableCell>
            <TableCell className="uppercase">{d.mode}</TableCell>
            <TableCell className="font-medium">{d.asset}</TableCell>
            <TableCell className="text-xs text-muted-foreground">paper {d.paper_id}</TableCell>
            <TableCell className="uppercase">
              {d.signal} {d.direction}
            </TableCell>
            <TableCell className={OUTCOME_CLASS[d.outcome] ?? "text-muted-foreground"}>{d.outcome}</TableCell>
            <Size decision={d} />
            <Price decision={d} />
            <ExitPnl decision={d} />
            <TableCell className="max-w-96 text-xs text-muted-foreground">
              {d.reason}
              {d.risk_reason ? ` — ${d.risk_reason}` : ""}
            </TableCell>
          </TableRow>
        ))}
      </TableBody>
    </Table>
  );
}
