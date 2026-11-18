import { TableCell, TableRow } from "@/components/ui/table";
import { formatNumber, formatPrice, formatUsd, pnlClass } from "@/lib/format";
import type { OpenPosition } from "@/types/portfolio";

import { ClosePositionButton } from "./close-position-button";
import { ClosedOnExchangeButton } from "./closed-on-exchange-button";
import { PnlPercent } from "./pnl-percent";
import { DIRECTION_CLASS } from "./direction";

function exitRule(p: OpenPosition): string {
  const parts: string[] = [];
  if (p.stop_loss_price) parts.push(`SL ${formatPrice(p.stop_loss_price)}`);
  if (p.take_profit_price) parts.push(`TP ${formatPrice(p.take_profit_price)}`);
  return parts.length > 0 ? parts.join(" / ") : "strategy exit";
}

export function OpenPositionRow({ position: p }: { position: OpenPosition }) {
  // The whole PnL on the average entry: the units sold so far plus the size held.
  const realized = Number(p.realized_pnl_usd);
  const total = p.unrealized_pnl_usd === null ? null : Number(p.unrealized_pnl_usd) + realized;
  return (
    <TableRow>
      <TableCell className="text-muted-foreground">{`#${String(p.paper_id)}`}</TableCell>
      <TableCell className="uppercase">{p.mode}</TableCell>
      <TableCell className="font-medium">{p.asset}</TableCell>
      <TableCell className={`uppercase ${DIRECTION_CLASS[p.direction] ?? ""}`}>{p.direction}</TableCell>
      <TableCell>{formatNumber(p.size)}</TableCell>
      <TableCell>{formatPrice(p.entry_price)}</TableCell>
      <TableCell>{formatPrice(p.current_price)}</TableCell>
      <TableCell className={pnlClass(total)}>
        {formatUsd(total)}
        <PnlPercent pnl={total === null ? null : String(total)} margin={p.margin_usd} />
        {realized !== 0 && (
          <div className="text-xs text-muted-foreground">
            {`held ${formatUsd(p.unrealized_pnl_usd)} · sold ${formatUsd(realized)}`}
          </div>
        )}
      </TableCell>
      <TableCell>{formatUsd(p.margin_usd)}</TableCell>
      <TableCell>{formatUsd(p.exposure_usd)}</TableCell>
      <TableCell className="text-xs text-muted-foreground">{exitRule(p)}</TableCell>
      <TableCell className="whitespace-nowrap">
        <ClosePositionButton position={p} />
        {p.mode === "live" && <ClosedOnExchangeButton position={p} />}
      </TableCell>
    </TableRow>
  );
}
