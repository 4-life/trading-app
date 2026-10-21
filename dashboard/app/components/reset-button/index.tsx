import { useFetcher } from "react-router";

import { ConfirmDialog } from "@/components/confirm-dialog";
import { Button } from "@/components/ui/button";
import type { ActionResult } from "@/types/action";

// Demo reset (docs/papers.md#demo-reset).
export function ResetButton() {
  const fetcher = useFetcher<ActionResult>();
  const busy = fetcher.state !== "idle";
  return (
    <div className="flex items-center gap-2">
      {fetcher.data?.error && <span className="text-xs text-destructive">{fetcher.data.error}</span>}
      <ConfirmDialog
        trigger={<Button variant="destructive" size="sm" disabled={busy} />}
        title="Reset demo?"
        description="Clears the demo balance, positions, orders, trading log and every paper's demo profitability. Live is not touched."
        confirmLabel="Reset demo"
        destructive
        onConfirm={() => void fetcher.submit({ intent: "reset" }, { method: "post" })}
      >
        {busy ? "Resetting…" : "Reset demo"}
      </ConfirmDialog>
    </div>
  );
}
