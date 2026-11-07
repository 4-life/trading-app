import { Popover } from "@base-ui/react/popover";
import { EllipsisVerticalIcon, PowerIcon, PowerOffIcon, RocketIcon, Trash2Icon } from "lucide-react";
import { useState } from "react";
import { useFetcher } from "react-router";

import { ConfirmDialog } from "@/components/confirm-dialog";
import { Button } from "@/components/ui/button";
import { isPreparing } from "@/lib/papers";
import type { ActionResult } from "@/types/action";
import type { Paper } from "@/types/paper";

import { EditPaperDialog } from "./edit-paper-modal";
import { isSweepable, SweepDialog } from "./sweep-modal";

export function PaperActions({ paper }: { paper: Paper }) {
  const fetcher = useFetcher<ActionResult>();
  const [open, setOpen] = useState(false);
  const busy = fetcher.state !== "idle";
  const submit = (intent: string) =>
    void fetcher.submit({ intent, paperId: String(paper.id) }, { method: "post" });
  // Same rules the API enforces (docs/papers.md#lifecycle): a scanner needs
  // no profit, its coins follow its mode.
  const scanned = paper.parent_id !== null;
  const backtestProfit = Number(paper.backtest_return_pct ?? 0) > 0;
  const canGoLive =
    paper.kind === "scanner" ||
    (!scanned && (Number(paper.profitability_demo) > 0 || backtestProfit));

  return (
    <div className="flex flex-wrap items-center gap-1">
      <Popover.Root open={open} onOpenChange={setOpen}>
        <Popover.Trigger
          render={<Button size="xs" variant="outline" aria-label={`Paper ${String(paper.id)} actions`} />}
        >
          <EllipsisVerticalIcon className="size-3.5" />
        </Popover.Trigger>
        {/* Kept mounted: the dialogs live in here, and stay open once it closes. */}
        <Popover.Portal keepMounted>
          <Popover.Positioner sideOffset={4} align="end" className="z-40">
            <Popover.Popup
              finalFocus={false}
              className="flex w-48 flex-col gap-1 rounded-lg border bg-background p-1.5 shadow-md [&>button]:w-full [&>button]:justify-start"
              onClick={() => setOpen(false)}
            >
              <EditPaperDialog paper={paper} />
              {isSweepable(paper) && <SweepDialog paper={paper} />}
              {paper.enabled && paper.mode === "demo" && (
                <ConfirmDialog
                  trigger={<Button size="xs" variant="outline" disabled={busy || !canGoLive} />}
                  title={`Switch paper ${paper.id} to live?`}
                  description={
                    paper.kind === "scanner"
                      ? `The coins scanner ${paper.id} picks from now on will trade real money on the exchange.`
                      : `${paper.executor} on ${paper.asset} will trade real money on the exchange.`
                  }
                  confirmLabel="Go live"
                  onConfirm={() => submit("paperLive")}
                >
                  <RocketIcon />
                  Go live
                </ConfirmDialog>
              )}
              {paper.enabled && paper.mode === "demo" && !canGoLive && (
                <span className="text-xs text-muted-foreground">
                  {scanned
                    ? "goes live with its scanner"
                    : "needs demo profit > 0% or a profitable backtest"}
                </span>
              )}
              {paper.enabled ? (
                <Button size="xs" variant="outline" disabled={busy} onClick={() => submit("paperDisable")}>
                  <PowerOffIcon />
                  Disable
                </Button>
              ) : (
                <>
                  <Button size="xs" variant="outline" disabled={busy} onClick={() => submit("paperEnable")}>
                    <PowerIcon />
                    Enable
                  </Button>
                  <ConfirmDialog
                    trigger={
                      <Button
                        size="xs"
                        variant="destructive"
                        disabled={busy || isPreparing(paper)}
                        title={isPreparing(paper) ? `paper is ${paper.prep_status ?? ""}` : undefined}
                      />
                    }
                    title={`Delete paper ${paper.id}?`}
                    description="Deletes the paper and its whole history: positions, orders, decisions, equity snapshots and risk events. This can't be undone."
                    confirmLabel="Delete"
                    destructive
                    onConfirm={() => submit("paperDelete")}
                  >
                    <Trash2Icon />
                    Delete
                  </ConfirmDialog>
                </>
              )}
            </Popover.Popup>
          </Popover.Positioner>
        </Popover.Portal>
      </Popover.Root>
      {fetcher.data?.error && <span className="text-xs text-destructive">{fetcher.data.error}</span>}
    </div>
  );
}
