import { Table, TableBody, TableCell, TableHead, TableHeader, TableRow } from "@/components/ui/table";
import { formatDateTime, formatPrice, formatUsd, pnlClass } from "@/lib/format";
import type { BacktestTrade } from "@/types/chart";

import { addCount, positionValue, sellCount, unitProfits } from "./backtest";
import { OPEN_AT_END } from "./constants";

// An averaging paper's backtest positions, one row each (docs/papers.md#averaging-papers);
// an averaging hedge paper's PnL also split into the long's and its shorts'.
export function AveragingPositions({ positions }: { positions: BacktestTrade[] }) {
  const rows = [...positions].sort((a, b) => a.opened_at.localeCompare(b.opened_at));
  const hedged = rows.some((t) => t.hedge_pnl_usd !== null);
  return (
    <div className="max-h-96 overflow-auto">
      <Table className="text-xs">
        <TableHeader>
          <TableRow>
            <TableHead>#</TableHead>
            <TableHead>Opened</TableHead>
            <TableHead>Closed</TableHead>
            <TableHead>Adds / sells</TableHead>
            <TableHead>Sold profit</TableHead>
            <TableHead>Peak margin</TableHead>
            <TableHead>Position $</TableHead>
            <TableHead>Avg entry → close</TableHead>
            {hedged && <TableHead>Long PnL</TableHead>}
            {hedged && <TableHead>Shorts PnL</TableHead>}
            <TableHead>{hedged ? "Total PnL" : "PnL"}</TableHead>
            <TableHead>% of margin</TableHead>
            <TableHead>Exit</TableHead>
          </TableRow>
        </TableHeader>
        <TableBody>
          {rows.map((t, k) => {
            const open = t.exit_reason === OPEN_AT_END;
            const pnl = Number(t.pnl_usd ?? 0);
            const margin = Number(t.margin_usd ?? 0);
            const pct = margin > 0 ? ((pnl / margin) * 100).toFixed(1) : "0";
            const value = positionValue(t);
            const sold = unitProfits(t).reduce((a, b) => a + b, 0);
            const shorts = Number(t.hedge_pnl_usd ?? 0);
            return (
              <TableRow key={t.opened_at}>
                <TableCell>{k + 1}</TableCell>
                <TableCell>{formatDateTime(t.opened_at)}</TableCell>
                <TableCell>
                  {open ? `test end ${formatDateTime(t.closed_at)}` : formatDateTime(t.closed_at)}
                </TableCell>
                <TableCell>
                  {addCount(t)} / {sellCount(t)}
                </TableCell>
                <TableCell className={pnlClass(String(sold))}>
                  {sellCount(t) > 0 ? formatUsd(sold) : "—"}
                </TableCell>
                <TableCell>{formatUsd(margin)}</TableCell>
                <TableCell>
                  {formatUsd(value.entry)} → {formatUsd(value.close)}
                </TableCell>
                <TableCell>
                  {formatPrice(t.entry_price)} → {formatPrice(t.close_price)}
                </TableCell>
                {hedged && (
                  <TableCell className={pnlClass(String(pnl - shorts))}>
                    {formatUsd(pnl - shorts)}
                  </TableCell>
                )}
                {hedged && (
                  <TableCell className={pnlClass(String(shorts))}>
                    {t.hedge_pnl_usd === null ? "—" : formatUsd(shorts)}
                  </TableCell>
                )}
                <TableCell className={pnlClass(String(pnl))}>
                  {open ? "unrealized " : ""}
                  {formatUsd(pnl)}
                </TableCell>
                <TableCell className={pnlClass(String(pnl))}>{pct}%</TableCell>
                <TableCell>{open ? "—" : t.exit_reason}</TableCell>
              </TableRow>
            );
          })}
        </TableBody>
      </Table>
    </div>
  );
}
