import { StarIcon } from "lucide-react";

import { TruncatedText } from "@/components/truncated-text";
import { Button } from "@/components/ui/button";
import { TableCell, TableRow } from "@/components/ui/table";
import { giveUp } from "@/lib/averaging";
import { formatPercent, formatUsd, pnlClass } from "@/lib/format";
import { AVERAGING_KINDS } from "@/constants/papers";
import type { Paper } from "@/types/paper";

import { PaperActions } from "./paper-actions";
import { PaperStatus } from "./paper-status";

const pct = (share: string) => `${String(Number(share) * 100)}%`;

// A leverage (or add leverage) above the asset's max at the exchange - the
// exchange won't take it; the backtest caps it (docs/market-data.md#market-limits).
function OverMaxLeverage({ paper }: { paper: Paper }) {
  if (paper.max_leverage === null) {
    return null;
  }
  const max = Number(paper.max_leverage);
  const over = Math.max(Number(paper.leverage), Number(paper.add_leverage ?? 0)) > max;
  if (!over) {
    return null;
  }
  return <div className="text-xs text-destructive">over the max ×{Math.floor(max)}</div>;
}

// The paper's position management in short (docs/papers.md#averaging-papers).
function ManagementSummary({ paper }: { paper: Paper }) {
  const parts: string[] = [];
  if (paper.initial_size_usd !== null) {
    parts.push(`$${String(Number(paper.initial_size_usd))}`);
  }
  if (AVERAGING_KINDS.includes(paper.kind) && paper.add_leverage !== null) {
    const size = paper.add_size_usd ?? paper.initial_size_usd;
    const sized = size === null ? "" : ` $${String(Number(size))}`;
    parts.push(`auto add${sized} ×${String(Number(paper.add_leverage))}`);
  }
  if (paper.intraday) {
    parts.push(paper.reopen_in_trend ? "intraday, reopen in trend" : "intraday");
  }
  if (paper.max_margin_usd !== null) {
    parts.push(`max $${String(Number(paper.max_margin_usd))}${paper.compound_margin ? " compounding" : ""}`);
  }
  if (paper.take_profit_pct !== null) {
    parts.push(`TP ${pct(paper.take_profit_pct)}`);
  }
  if (paper.max_drawdown_pct !== null) {
    parts.push(`DD ${pct(paper.max_drawdown_pct)}`);
  }
  if (AVERAGING_KINDS.includes(paper.kind)) {
    const initial = Number(paper.initial_size_usd ?? 0);
    const auto = giveUp(
      Number(paper.leverage),
      initial,
      Number(paper.add_size_usd ?? initial),
      Number(paper.add_leverage ?? 0),
      Number(paper.max_margin_usd ?? 0),
      paper.maintenance_margin === null ? null : Number(paper.maintenance_margin),
    );
    if (auto !== null) {
      parts.push(`gives up at −${(auto.drop * 100).toFixed(1)}%`);
    }
  }
  if (parts.length === 0) {
    return null;
  }
  return <TruncatedText text={parts.join(" · ")} className="max-w-64 text-xs text-muted-foreground" />;
}

// The current backtest's net over its closed trades: an averaging paper's in
// USD, the others' in % of price - as on its chart.
function BacktestNet({ paper }: { paper: Paper }) {
  const net = AVERAGING_KINDS.includes(paper.kind) ? paper.backtest_net_usd : paper.backtest_return_pct;
  if (net === null) {
    return <TableCell className="text-muted-foreground">—</TableCell>;
  }
  return (
    <TableCell className={pnlClass(net)}>
      {AVERAGING_KINDS.includes(paper.kind) ? formatUsd(net) : formatPercent(net)}
    </TableCell>
  );
}

// The star marking the paper as a favourite in this browser.
function FavouriteStar({ favourite, onToggle }: { favourite: boolean; onToggle: () => void }) {
  return (
    <Button
      variant="ghost"
      size="icon-xs"
      aria-label={favourite ? "Remove from favourites" : "Add to favourites"}
      aria-pressed={favourite}
      onClick={onToggle}
    >
      <StarIcon className={favourite ? "fill-amber-400 text-amber-400" : "text-muted-foreground"} />
    </Button>
  );
}

export function PaperRow({
  paper,
  favourite,
  onToggleFavourite,
}: {
  paper: Paper;
  favourite: boolean;
  onToggleFavourite: () => void;
}) {
  return (
    <TableRow className={paper.enabled ? undefined : "opacity-60"}>
      <TableCell>
        <div className="flex items-center gap-1">
          <FavouriteStar favourite={favourite} onToggle={onToggleFavourite} />
          {paper.id}
        </div>
      </TableCell>
      <TableCell>
        <TruncatedText text={`${paper.kind} / ${paper.executor}`} className="max-w-48" />
      </TableCell>
      <TableCell className="font-medium">
        {paper.kind === "scanner" ? (
          <span className="text-sky-400">market (scanner)</span>
        ) : (
          paper.asset
        )}
        {paper.parent_id !== null && (
          <span className="ml-1 text-xs font-normal text-muted-foreground">
            auto · #{paper.parent_id}
          </span>
        )}
      </TableCell>
      <TableCell>{paper.timeframe}</TableCell>
      <TableCell className="uppercase">{paper.direction}</TableCell>
      <TableCell>
        {Number(paper.leverage)}×
        <OverMaxLeverage paper={paper} />
        <ManagementSummary paper={paper} />
      </TableCell>
      <TableCell className={paper.mode === "live" ? "font-semibold text-amber-400" : undefined}>
        {paper.mode}
      </TableCell>
      <TableCell className={pnlClass(paper.profitability_demo)}>
        {formatPercent(paper.profitability_demo)}
      </TableCell>
      <TableCell className={pnlClass(paper.profitability_live)}>
        {formatPercent(paper.profitability_live)}
      </TableCell>
      <BacktestNet paper={paper} />
      <TableCell className="text-xs">
        <PaperStatus paper={paper} />
      </TableCell>
      <TableCell>
        <PaperActions paper={paper} />
      </TableCell>
    </TableRow>
  );
}
