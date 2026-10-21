import { useFetcher } from "react-router";

import { ConfirmDialog } from "@/components/confirm-dialog";
import { Button } from "@/components/ui/button";
import { isPreparing } from "@/lib/papers";
import type { ActionResult } from "@/types/action";
import type { Paper } from "@/types/paper";

import { EditPaperDialog } from "./edit-paper-dialog";

export function PaperActions({ paper }: { paper: Paper }) {
  const fetcher = useFetcher<ActionResult>();
  const busy = fetcher.state !== "idle";
  const submit = (intent: string) =>
    void fetcher.submit({ intent, paperId: String(paper.id) }, { method: "post" });
  // Same rules the API enforces (docs/papers.md#lifecycle).
  const scanned = paper.kind === "scanner" || paper.parent_id !== null;
  const backtestProfit = Number(paper.backtest_return_pct ?? 0) > 0;
  const canGoLive = !scanned && (Number(paper.profitability_demo) > 0 || backtestProfit);

  return (
    <div className="flex flex-wrap items-center gap-1">
      <EditPaperDialog paper={paper} />
      {paper.enabled && paper.mode === "demo" && (
        <ConfirmDialog
          trigger={<Button size="xs" variant="outline" disabled={busy || !canGoLive} />}
          title={`Switch paper ${paper.id} to live?`}
          description={`${paper.executor} on ${paper.asset} will trade real money on the exchange.`}
          confirmLabel="Go live"
          onConfirm={() => submit("paperLive")}
        >
          Go live
        </ConfirmDialog>
      )}
      {paper.enabled && paper.mode === "demo" && !canGoLive && (
        <span className="text-xs text-muted-foreground">
          {scanned
            ? "goes live on its own with an exchange API"
            : "needs demo profit > 0% or a profitable backtest"}
        </span>
      )}
      {paper.enabled ? (
        <Button size="xs" variant="outline" disabled={busy} onClick={() => submit("paperDisable")}>
          Disable
        </Button>
      ) : (
        <>
          <Button size="xs" variant="outline" disabled={busy} onClick={() => submit("paperEnable")}>
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
            Delete
          </ConfirmDialog>
        </>
      )}
      {fetcher.data?.error && <span className="text-xs text-destructive">{fetcher.data.error}</span>}
    </div>
  );
}
