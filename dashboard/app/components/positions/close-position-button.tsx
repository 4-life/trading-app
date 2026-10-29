import { X } from "lucide-react";
import { useFetcher } from "react-router";

import { ConfirmDialog } from "@/components/confirm-dialog";
import { Button } from "@/components/ui/button";
import type { ActionResult } from "@/types/action";
import type { OpenPosition } from "@/types/portfolio";

// Queues a manual close (docs/api.md - POST /positions/{id}/close): the paper
// disabled with it, or kept running.
export function ClosePositionButton({ position }: { position: OpenPosition }) {
  const fetcher = useFetcher<ActionResult>();
  const label = `${position.mode} ${position.direction} ${position.asset}`;
  const close = (disablePaper: boolean) =>
    void fetcher.submit(
      { intent: "closePosition", positionId: String(position.id), disablePaper: String(disablePaper) },
      { method: "post" },
    );
  return (
    <>
      <ConfirmDialog
        trigger={
          <Button
            variant="ghost"
            size="icon-xs"
            title={`Close ${label}`}
            disabled={fetcher.state !== "idle"}
          />
        }
        title={`Close ${label}?`}
        description="Queues an exit at the market price. It goes through the risk engine and the execution engine like any other close. Disabling the paper stops it from opening a new position."
        confirmLabel="Close and disable paper"
        destructive
        onConfirm={() => close(true)}
        alternative={{ label: "Just close", onConfirm: () => close(false) }}
      >
        <X />
      </ConfirmDialog>
      {fetcher.data?.error && <span className="text-xs text-destructive">{fetcher.data.error}</span>}
    </>
  );
}
