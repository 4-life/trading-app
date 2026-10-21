import { X } from "lucide-react";
import { useFetcher } from "react-router";

import { ConfirmDialog } from "@/components/confirm-dialog";
import { Button } from "@/components/ui/button";
import type { ActionResult } from "@/types/action";
import type { OpenPosition } from "@/types/portfolio";

// Queues a manual close (docs/api.md - POST /positions/{id}/close).
export function ClosePositionButton({ position }: { position: OpenPosition }) {
  const fetcher = useFetcher<ActionResult>();
  const label = `${position.mode} ${position.direction} ${position.asset}`;
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
        description="Queues an exit at the market price. It goes through the risk engine and the execution engine like any other close."
        confirmLabel="Close position"
        destructive
        onConfirm={() =>
          void fetcher.submit(
            { intent: "closePosition", positionId: String(position.id) },
            { method: "post" },
          )
        }
      >
        <X />
      </ConfirmDialog>
      {fetcher.data?.error && <span className="text-xs text-destructive">{fetcher.data.error}</span>}
    </>
  );
}
