import { Loader2 } from "lucide-react";
import { useState } from "react";
import { useFetcher } from "react-router";

import { Button } from "@/components/ui/button";
import { Checkbox } from "@/components/ui/checkbox";
import {
  Dialog,
  DialogContent,
  DialogDescription,
  DialogHeader,
  DialogTitle,
  DialogTrigger,
} from "@/components/ui/dialog";
import { AVERAGING_KINDS } from "@/constants/papers";
import { formatUsd } from "@/lib/format";
import { FIELD_CLASS } from "@/lib/styles";
import type { ActionResult } from "@/types/action";
import type { Paper } from "@/types/paper";
import type { SweepBatch } from "@/types/sweep";

import { SWEEP_DEFAULT_MAX_MARGIN } from "./constants";
import { useSweepBatch } from "./hooks/use-sweep-batch";

// Several averaging papers' settings sweeps, one after another, each on the
// same budget - started overnight (docs/dashboard.md#papers). Each paper's
// results are in its Sweep dialog.
export function BatchSweepDialog({ papers }: { papers: Paper[] }) {
  const [open, setOpen] = useState(false);
  const fetcher = useFetcher<ActionResult>();
  const stopFetcher = useFetcher<ActionResult>();
  const { batch, running, loadError, checking } = useSweepBatch(
    open,
    fetcher.data ?? stopFetcher.data,
  );
  const averaging = papers.filter((p) => AVERAGING_KINDS.includes(p.kind));
  const starting = fetcher.state !== "idle";
  const error = fetcher.data?.error ?? stopFetcher.data?.error ?? loadError;
  return (
    <Dialog open={open} onOpenChange={setOpen}>
      <DialogTrigger render={<Button size="sm" variant="outline" />}>Batch sweep</DialogTrigger>
      <DialogContent className="sm:max-w-4xl">
        <DialogHeader>
          <DialogTitle>Batch sweep</DialogTitle>
          <DialogDescription>
            Each picked paper's settings sweep, one after another, on the same budget each -
            fixed and compounding. Results in each paper's Sweep dialog.
          </DialogDescription>
        </DialogHeader>
        {batch && <BatchProgress batch={batch} papers={papers} />}
        {running ? (
          <Button
            variant="outline"
            disabled={stopFetcher.state !== "idle"}
            onClick={() => {
              void stopFetcher.submit({ intent: "stopBatch" }, { method: "post" });
            }}
          >
            {stopFetcher.state === "idle" ? "Stop batch" : "Stopping…"}
          </Button>
        ) : (
          <fetcher.Form method="post" className="space-y-3">
            <input type="hidden" name="intent" value="startBatch" />
            <div className="grid gap-x-4 gap-y-1 rounded-md border p-2 sm:grid-cols-3">
              {averaging.length === 0 ? (
                <p className="text-sm text-muted-foreground">No averaging papers</p>
              ) : (
                averaging.map((p) => (
                  <label key={p.id} className="flex items-center gap-2 text-sm">
                    <Checkbox name="paperIds" value={String(p.id)} />
                    {`#${String(p.id)} ${p.executor} ${p.asset} ${p.timeframe} ${p.mode}`}
                  </label>
                ))
              )}
            </div>
            <label className="flex flex-col gap-0.5 text-xs text-muted-foreground">
              Budget per paper $
              <input
                name="max_margin"
                type="number"
                step="1"
                min="1"
                required
                defaultValue={SWEEP_DEFAULT_MAX_MARGIN}
                className={`${FIELD_CLASS} w-28`}
              />
            </label>
            <Button type="submit" disabled={starting || checking || averaging.length === 0}>
              {starting ? (
                <>
                  <Loader2 className="size-4 animate-spin" />
                  Starting…
                </>
              ) : (
                "Start batch"
              )}
            </Button>
          </fetcher.Form>
        )}
        {error && <p className="text-sm text-destructive">{error}</p>}
      </DialogContent>
    </Dialog>
  );
}

function BatchProgress({ batch, papers }: { batch: SweepBatch; papers: Paper[] }) {
  const name = (id: number) => {
    const p = papers.find((x) => x.id === id);
    return p ? `#${String(id)} ${p.executor} ${p.asset}` : `#${String(id)}`;
  };
  const total = batch.paper_ids.length;
  const current = batch.current;
  return (
    <div className="space-y-1 rounded-md border p-2 text-xs">
      <p className="font-medium">
        {batch.status === "running"
          ? `Running: paper ${String(batch.papers_done + 1)} of ${String(total)}`
          : batch.status === "done"
            ? `Done: ${String(total)} papers`
            : batch.status === "stopped"
              ? `Stopped: ${String(batch.papers_done)} of ${String(total)} papers done`
              : `Failed: ${batch.error ?? "unknown"}`}
        {` · ${formatUsd(batch.max_margin)} each`}
      </p>
      {batch.status === "running" && batch.current_paper_id !== null && (
        <p className="flex items-center gap-1 text-muted-foreground">
          <Loader2 className="size-3 animate-spin" />
          {name(batch.current_paper_id)}
          {current && current.runs_total > 0
            ? ` · ${current.runs_done.toLocaleString()} of ${current.runs_total.toLocaleString()} runs`
            : " · loading the candles"}
        </p>
      )}
      <p className="text-muted-foreground">{batch.paper_ids.map(name).join(", ")}</p>
    </div>
  );
}
