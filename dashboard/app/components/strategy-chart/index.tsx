import { Loader2 } from "lucide-react";
import { lazy, Suspense, useEffect, useState } from "react";
import { useFetchers, useNavigate, useSearchParams } from "react-router";

import { Accordion, AccordionContent, AccordionItem, AccordionTrigger } from "@/components/ui/accordion";
import { Card, CardContent, CardHeader, CardTitle } from "@/components/ui/card";
import { FIELD_CLASS } from "@/lib/styles";
import { ASSET_KINDS, AVERAGING_KINDS } from "@/constants/papers";
import { isPreparing } from "@/lib/papers";
import type { BacktestTrade, PaperChart } from "@/types/chart";
import type { Paper } from "@/types/paper";

import { addCount, positionValue } from "./backtest";
import { OPEN_AT_END } from "./constants";
import { AveragingPositions } from "./averaging-positions";

// The chart library needs the browser: the chart module is loaded on the client
// only, after mount, and kept out of the main bundle.
const StrategyChart = lazy(() => import("./strategy-chart"));

const HEIGHT_CLASS = "h-[560px]";

const signed = (x: number, digits = 1) => `${x >= 0 ? "+" : ""}${x.toFixed(digits)}%`;
const tone = (x: number) => (x >= 0 ? "text-green-500" : "text-red-500");

// Totals of the temporary backtest (docs/vwap-strategy-engine.md#backtest):
// % of price per trade; at the paper's leverage compounded (each trade on
// the whole margin) with its worst peak-to-trough drop; and per month.
const LEVERAGES = [1, 3, 5, 10];

// Trades in order, each on the whole margin at `leverage` (equity can't go below 0).
function compound(returns: number[], leverage: number): { total: number; maxDrawdown: number } {
  let equity = 1;
  let peak = 1;
  let maxDrawdown = 0;
  for (const r of returns) {
    equity *= Math.max(0, 1 + (r * leverage) / 100);
    peak = Math.max(peak, equity);
    maxDrawdown = Math.min(maxDrawdown, peak > 0 ? equity / peak - 1 : -1);
  }
  return { total: equity - 1, maxDrawdown };
}

function BacktestSummary({ chart, leverage }: { chart: PaperChart; leverage: number }) {
  const trades = [...chart.backtest].sort((a, b) => a.closed_at.localeCompare(b.closed_at));
  const returns = trades.map((t) => Number(t.return_pct));
  const net = returns.reduce((a, b) => a + b, 0);
  const wins = returns.filter((r) => r > 0).length;
  const { total, maxDrawdown } = compound(returns, leverage);
  const leverages = [...new Set([...LEVERAGES, leverage])].sort((a, b) => a - b);
  const months = new Map<string, { n: number; won: number; net: number }>();
  trades.forEach((t, k) => {
    const key = t.closed_at.slice(0, 7);
    const m = months.get(key) ?? { n: 0, won: 0, net: 0 };
    m.n += 1;
    m.won += returns[k] > 0 ? 1 : 0;
    m.net += returns[k];
    months.set(key, m);
  });
  return (
    <div className="space-y-1 text-xs text-muted-foreground">
      <p>
        Backtest (temporary): {returns.length} trades, {wins} won (
        {Math.round((wins / returns.length) * 100)}%), net{" "}
        <span className={tone(net)}>{signed(net, 2)}</span> of price after fees · at {leverage}×
        compounded <span className={tone(total)}>{signed(total * 100)}</span>, max
        drawdown <span className="text-red-500">{signed(maxDrawdown * 100)}</span>.
      </p>
      <p className="flex flex-wrap gap-x-3">
        <span>Compounded by leverage (max drawdown):</span>
        {leverages.map((lev) => {
          const c = compound(returns, lev);
          return (
            <span key={lev} className={lev === leverage ? "font-semibold text-foreground" : undefined}>
              {lev}× <span className={tone(c.total)}>{signed(c.total * 100)}</span> (
              <span className="text-red-500">{signed(c.maxDrawdown * 100)}</span>)
            </span>
          );
        })}
      </p>
      <p className="flex flex-wrap gap-x-3">
        {[...months.entries()].map(([month, m]) => (
          <span key={month}>
            {month}: {m.n} trades, {m.won} won,{" "}
            <span className={tone(m.net)}>{signed(m.net, 2)}</span>
          </span>
        ))}
      </p>
    </div>
  );
}

const usd = (x: number) => `${x >= 0 ? "+" : "-"}$${Math.abs(x).toFixed(2)}`;

// An averaging paper's backtest (docs/papers.md#averaging-papers): one row per
// position, in USD - its leverage changes with every add, so the per-trade
// "% of price at the paper's leverage" figures above don't apply.
function AveragingSummary({ chart }: { chart: PaperChart }) {
  // The position still open on the last candle is shown apart: its result isn't realized.
  const open = chart.backtest.find((t) => t.exit_reason === OPEN_AT_END);
  const trades = chart.backtest
    .filter((t) => t.exit_reason !== OPEN_AT_END)
    .sort((a, b) => a.closed_at.localeCompare(b.closed_at));
  const pnl = trades.map((t) => Number(t.pnl_usd ?? 0));
  const margin = trades.map((t) => Number(t.margin_usd ?? 0));
  const net = pnl.reduce((a, b) => a + b, 0);
  // The cash the strategy needed: the most any position locked at once.
  const peak = Math.max(0, ...margin);
  const wins = pnl.filter((x) => x > 0).length;
  const adds = trades.reduce((a, t) => a + addCount(t), 0);
  const exits = new Map<string, number>();
  const months = new Map<string, { n: number; won: number; net: number }>();
  trades.forEach((t, k) => {
    exits.set(t.exit_reason, (exits.get(t.exit_reason) ?? 0) + 1);
    const key = t.closed_at.slice(0, 7);
    const m = months.get(key) ?? { n: 0, won: 0, net: 0 };
    m.n += 1;
    m.won += pnl[k] > 0 ? 1 : 0;
    m.net += pnl[k];
    months.set(key, m);
  });
  return (
    <div className="space-y-1 text-xs text-muted-foreground">
      {trades.length === 0 ? (
        <p>Averaging backtest (temporary): no closed positions yet.</p>
      ) : (
        <p>
          Averaging backtest (temporary): {trades.length} positions, {wins} won (
          {Math.round((wins / trades.length) * 100)}%), net <span className={tone(net)}>{usd(net)}</span>{" "}
          · most margin locked at once ${peak.toFixed(2)} (
          <span className={tone(net)}>{signed(peak > 0 ? (net / peak) * 100 : 0)}</span> on it) ·{" "}
          {(adds / trades.length).toFixed(1)} adds
          per position · exits:{" "}
          {[...exits.entries()].map(([reason, n]) => `${reason} ${String(n)}`).join(", ")}.
        </p>
      )}
      {open && <OpenPosition position={open} />}
      {open && trades.length > 0 && (
        <p className="text-foreground">
          Total <span className={tone(net + Number(open.pnl_usd ?? 0))}>
            {usd(net + Number(open.pnl_usd ?? 0))}
          </span>{" "}
          = closed <span className={tone(net)}>{usd(net)}</span> + open{" "}
          <span className={tone(Number(open.pnl_usd ?? 0))}>{usd(Number(open.pnl_usd ?? 0))}</span>{" "}
          (unrealized, valued at the test end).
        </p>
      )}
      <p className="flex flex-wrap gap-x-3">
        {[...months.entries()].map(([month, m]) => (
          <span key={month}>
            {month}: {m.n} positions, {m.won} won, <span className={tone(m.net)}>{usd(m.net)}</span>
          </span>
        ))}
      </p>
    </div>
  );
}

// The averaging backtest's position still open when the backtest ended (its last candle).
function OpenPosition({ position }: { position: BacktestTrade }) {
  const pnl = Number(position.pnl_usd ?? 0);
  const margin = Number(position.margin_usd ?? 0);
  const value = positionValue(position);
  return (
    <p className="text-foreground">
      Open at the test end ({position.closed_at.slice(0, 10)}): since {position.opened_at.slice(0, 10)},{" "}
      {addCount(position)}{" "}
      adds, avg {Number(position.entry_price).toFixed(2)} → {Number(position.close_price).toFixed(2)},
      position ${value.entry.toFixed(2)} → ${value.close.toFixed(2)}, peak margin ${margin.toFixed(2)},
      unrealized there <span className={tone(pnl)}>{usd(pnl)}</span> (
      <span className={tone(pnl)}>{signed(margin > 0 ? (pnl / margin) * 100 : 0)}</span>)
      .
    </p>
  );
}

// One paper's chart (docs/dashboard.md#strategy-chart). The paper is picked
// in the URL (?chartPaper=) - only its data is loaded and only one chart
// exists on the page.
export function StrategyChartCard({
  papers,
  chart,
}: {
  papers: Paper[] | null;
  chart: PaperChart | null;
}) {
  const [params] = useSearchParams();
  const navigate = useNavigate();
  // The paper just picked, until its chart data arrives (the page's data
  // streams in - the navigation itself finishes at once).
  const [picked, setPicked] = useState<number | null>(null);
  useEffect(() => setPicked(null), [chart]);
  const switching = picked !== null && picked !== chart?.paper_id;
  const [mounted, setMounted] = useState(false);
  useEffect(() => setMounted(true), []);
  // Saving an averaging paper's settings re-runs its backtest within the save:
  // the papers being saved show the backtest loader meanwhile.
  const saving = new Set(
    useFetchers()
      .filter((f) => f.formData?.get("intent") === "updatePaper")
      .map((f) => Number(f.formData?.get("paperId"))),
  );

  // A scanner paper has no candles of its own - its single papers do.
  const chartPapers = (papers ?? []).filter((p) => ASSET_KINDS.includes(p.kind));
  if (chartPapers.length === 0) return null;
  const selected = chartPapers.find((p) => p.id === chart?.paper_id) ?? null;
  const averaging = selected !== null && AVERAGING_KINDS.includes(selected.kind);
  const backtesting = averaging && saving.has(selected.id);
  const preparing = selected !== null && (isPreparing(selected) || backtesting);

  return (
    <Card>
      <CardHeader className="flex flex-row flex-wrap items-center justify-between gap-2">
        <CardTitle>
          Chart{chart ? ` — ${chart.asset} ${chart.timeframe} ${chart.kind} / ${chart.executor}` : ""}
        </CardTitle>
        {/* Never wider than the card: a long option is cut, its full text in the open list. */}
        <select
          aria-label="Paper"
          className={`${FIELD_CLASS} w-full min-w-0 truncate sm:w-auto sm:max-w-md`}
          value={picked ?? chart?.paper_id ?? ""}
          onChange={(e) => {
            const next = new URLSearchParams(params);
            next.set("chartPaper", e.target.value);
            setPicked(Number(e.target.value));
            void navigate({ search: `?${next.toString()}` }, { preventScrollReset: true });
          }}
        >
          {chartPapers.map((p) => (
            <option key={p.id} value={p.id}>
              #{p.id} {p.kind} / {p.executor} {p.asset} {p.timeframe} {p.mode}
              {p.enabled ? "" : " (disabled)"}
            </option>
          ))}
        </select>
      </CardHeader>
      <CardContent className="relative">
        {switching && (
          // Over the old chart (dimmed below) until the new one's data is in.
          <div className="absolute inset-0 z-10 flex items-center justify-center gap-2 text-sm text-sky-400">
            <Loader2 className="size-4 animate-spin" />
            Loading chart…
          </div>
        )}
        <div
          className={
            `space-y-2 transition-opacity ${switching ? "pointer-events-none opacity-40" : ""}`
          }
        >
          {chart &&
            chart.backtest.length > 0 &&
            !preparing &&
            (averaging ? (
              <AveragingSummary chart={chart} />
            ) : (
              <BacktestSummary
                chart={chart}
                leverage={Number(chartPapers.find((p) => p.id === chart.paper_id)?.leverage ?? 1)}
              />
            ))}
          {preparing ? (
            <div
              className={`${HEIGHT_CLASS} flex items-center justify-center gap-2 text-sm text-sky-400`}
            >
              <Loader2 className="size-4 animate-spin" />
              {selected?.prep_status === "backfilling"
                ? "Backfilling history…"
                : "Running the backtest…"}
            </div>
          ) : chart === null ? (
            <p className="text-sm text-muted-foreground">Unavailable</p>
          ) : mounted ? (
            <Suspense fallback={<div className={HEIGHT_CLASS} />}>
              {/* key: switching papers destroys the old chart instead of reusing it */}
              <StrategyChart key={chart.paper_id} chart={chart} />
            </Suspense>
          ) : (
            <div className={HEIGHT_CLASS} />
          )}
          {chart && !preparing && averaging && chart.backtest.length > 0 && (
            // The backtest log, collapsed by default.
            <Accordion>
              <AccordionItem>
                <AccordionTrigger>Backtest log ({chart.backtest.length} positions)</AccordionTrigger>
                <AccordionContent>
                  <AveragingPositions positions={chart.backtest} />
                </AccordionContent>
              </AccordionItem>
            </Accordion>
          )}
        </div>
      </CardContent>
    </Card>
  );
}
