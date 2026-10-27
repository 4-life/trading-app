import { Loader2 } from "lucide-react";
import { useState } from "react";
import { useFetcher } from "react-router";

import { Button } from "@/components/ui/button";
import { Switch } from "@/components/ui/switch";
import { formatUsd } from "@/lib/format";
import { FIELD_CLASS } from "@/lib/styles";
import type { ActionResult } from "@/types/action";
import type { Paper } from "@/types/paper";
import type { ExitSweepRun, SweepRun } from "@/types/sweep";

import { AveragingRunsTable } from "./averaging-runs-table";
import {
  EXIT_SWEEP_SORTS,
  SWEEP_DEFAULT_MAX_LEVERAGE,
  SWEEP_DEFAULT_MAX_MARGIN,
  SWEEP_MIN_HEADROOM,
  SWEEP_SORTS,
} from "../constants";
import { ExitRunsTable } from "./exit-runs-table";
import { useSweepStatus } from "./hooks/use-sweep-status";

// "Find best params": a paper's settings sweep (docs/api.md) - an averaging
// paper's (leverage, size, take-profit, intraday) or a single paper's
// (leverage, stop-loss, take-profit). It
// runs in the API's background, storing each run's stats; this reads its
// latest one and the best 5 runs so far by the stat picked (useSweepStatus),
// polled while it runs. One sweep at a time on the server.
export function SweepPanel({ paper }: { paper: Paper }) {
  const fetcher = useFetcher<ActionResult>();
  const stopFetcher = useFetcher<ActionResult>();
  const single = paper.kind === "single";
  const sorts = single ? EXIT_SWEEP_SORTS : SWEEP_SORTS;
  const [sort, setSort] = useState<string>(sorts[0][0]);
  // An averaging paper's drained and tight runs (docs/papers.md#averaging-papers): hidden by default.
  const [robust, setRobust] = useState(true);
  const { sweep, runs, compoundRuns, starting, running, busyPaper, loadError, checking } =
    useSweepStatus(paper, sort, robust, {
    starting: fetcher.state !== "idle",
    started: fetcher.data,
    stopped: stopFetcher.data,
  });
  const error = fetcher.data?.error ?? stopFetcher.data?.error ?? loadError;
  // The move a run must survive (null: not measured).
  const needed =
    !sweep || sweep.adverse_move_pct === null
      ? null
      : Number(sweep.adverse_move_pct) * sweep.survival_margin;
  return (
    <div className="space-y-2 border-t pt-3">
      <fetcher.Form method="post" className="flex flex-wrap items-end gap-2">
        <input type="hidden" name="intent" value="sweepPaper" />
        <input type="hidden" name="paperId" value={paper.id} />
        <label className="flex flex-col gap-0.5 text-xs text-muted-foreground">
          Max leverage
          <input
            name="max_leverage"
            type="number"
            step="1"
            min="1"
            defaultValue={Math.floor(Number(paper.max_leverage ?? SWEEP_DEFAULT_MAX_LEVERAGE))}
            className={`${FIELD_CLASS} w-24`}
          />
        </label>
        {!single && (
          <label className="flex flex-col gap-0.5 text-xs text-muted-foreground">
            Max margin $
            <input
              name="max_margin"
              type="number"
              step="1"
              min="1"
              defaultValue={Number(paper.max_margin_usd ?? SWEEP_DEFAULT_MAX_MARGIN)}
              className={`${FIELD_CLASS} w-28`}
            />
          </label>
        )}
        <Button
          type="submit"
          size="sm"
          variant="outline"
          disabled={running || busyPaper !== null || checking}
        >
          {running ? (
            <>
              <Loader2 className="size-4 animate-spin" />
              Running…
            </>
          ) : (
            "Find best params"
          )}
        </Button>
        {sweep?.status === "running" && (
          <Button
            type="button"
            size="sm"
            variant="outline"
            disabled={stopFetcher.state !== "idle"}
            onClick={() => {
              void stopFetcher.submit(
                { intent: "stopSweep", paperId: String(paper.id) },
                { method: "post" },
              );
            }}
          >
            Stop
          </Button>
        )}
      </fetcher.Form>
      {busyPaper !== null && (
        <p className="text-xs text-muted-foreground">
          {`Paper ${String(busyPaper)} is sweeping - one at a time, wait for it to finish`}
        </p>
      )}
      {error && <p className="text-sm text-destructive">{error}</p>}
      {starting && (
        <p className="flex items-center gap-1 text-xs text-muted-foreground">
          <Loader2 className="size-3 animate-spin" />
          Starting…
        </p>
      )}
      {sweep && (
        <div className="space-y-1 text-xs">
          <p className="text-muted-foreground">
            {sweep.status === "running"
              ? sweep.runs_total > 0
                ? `Testing… ${sweep.runs_done.toLocaleString()} of ${sweep.runs_total.toLocaleString()} runs`
                : "Testing… loading the candles"
              : sweep.status === "done"
                ? `Done: ${sweep.runs_done.toLocaleString()} runs`
                : sweep.status === "stopped"
                  ? `Stopped: ${sweep.runs_done.toLocaleString()} of ${sweep.runs_total.toLocaleString()} runs`
                  : `Failed: ${sweep.error ?? "unknown"} (${sweep.runs_done.toLocaleString()} runs stored)`}
            {sweep.start && sweep.end
              ? ` · ${sweep.start} → ${sweep.end}, train before ${sweep.split ?? "—"}`
              : ""}
            {/* The asset's max can be 1 / its margin share (×30.03): rounded down, one decimal at most. */}
            {` · max ×${String(Math.floor(Number(sweep.max_leverage) * 10) / 10)}`}
            {sweep.max_margin === null ? "" : `, max margin ${formatUsd(sweep.max_margin)}`}
          </p>
          {!single && sweep.runs_done > 0 && (
            <p className="text-muted-foreground">
              {`Of ${sweep.runs_done.toLocaleString()} runs: ` +
                `${sweep.drained_runs.toLocaleString()} drained (out of cash) · ` +
                `${sweep.tight_runs.toLocaleString()} tight · ` +
                `${sweep.fragile_runs.toLocaleString()} fragile`}
            </p>
          )}
          {needed !== null && sweep.adverse_move_pct !== null && (
            <p className="text-muted-foreground">
              {`${paper.asset}'s worst move against an entry within 7 days: ` +
                `${(Number(sweep.adverse_move_pct) * 100).toFixed(1)}% or less in 95% of cases. ` +
                `Runs need to survive ${(needed * 100).toFixed(1)}% ` +
                `(${String(sweep.survival_margin)}×) - fragile below that.`}
            </p>
          )}
          {!single && (
            <label className="flex w-fit cursor-pointer items-center gap-1.5 text-muted-foreground">
              <Switch checked={robust} onCheckedChange={setRobust} />
              Hide drained, tight (under {SWEEP_MIN_HEADROOM * 100}% of the max margin left) and fragile
              runs
            </label>
          )}
          {runs.length === 0 && compoundRuns.length > 0 && (
            <p className="text-muted-foreground">No fixed-budget run left.</p>
          )}
          {(runs.length > 0 || compoundRuns.length > 0) && (
            <>
              <label className="flex items-center gap-1 text-muted-foreground">
                {sweep.status === "running" ? "Best so far by" : "Best by"}
                <select
                  className={FIELD_CLASS}
                  value={sort}
                  onChange={(e) => setSort(e.target.value)}
                >
                  {sorts.map(([key, label]) => (
                    <option key={key} value={key}>
                      {label}
                    </option>
                  ))}
                </select>
              </label>
              {single ? (
                <ExitRunsTable runs={runs as ExitSweepRun[]} />
              ) : (
                <>
                  <p className="font-medium">Fixed budget - profits banked</p>
                  <AveragingRunsTable
                    runs={runs as SweepRun[]}
                    maxMargin={sweep.max_margin}
                    needed={needed}
                  />
                  <p className="pt-2 font-medium">Compounding - max margin + realized PnL</p>
                  <AveragingRunsTable runs={compoundRuns} maxMargin={null} needed={needed} />
                </>
              )}
            </>
          )}
        </div>
      )}
    </div>
  );
}
