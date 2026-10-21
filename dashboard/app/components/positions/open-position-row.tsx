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
  return (
    <TableRow>
      <TableCell className="uppercase">{p.mode}</TableCell>
      <TableCell className="font-medium">{p.asset}</TableCell>
      <TableCell className={`uppercase ${DIRECTION_CLASS[p.direction] ?? ""}`}>{p.direction}</TableCell>
      <TableCell>{formatNumber(p.size)}</TableCell>
      <TableCell>{formatPrice(p.entry_price)}</TableCell>
      <TableCell>{formatPrice(p.current_price)}</TableCell>
      <TableCell className={pnlClass(p.unrealized_pnl_usd)}>
        {formatUsd(p.unrealized_pnl_usd)}
        <PnlPercent pnl={p.unrealized_pnl_usd} margin={p.margin_usd} />
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
