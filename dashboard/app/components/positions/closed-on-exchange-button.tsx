import { Ban } from "lucide-react";
import { useEffect, useState } from "react";
import { useFetcher } from "react-router";

import { Button } from "@/components/ui/button";
import {
  Dialog,
  DialogClose,
  DialogContent,
  DialogDescription,
  DialogFooter,
  DialogHeader,
  DialogTitle,
  DialogTrigger,
} from "@/components/ui/dialog";
import { FIELD_CLASS } from "@/lib/styles";
import type { ActionResult } from "@/types/action";
import type { OpenPosition } from "@/types/portfolio";

// A live position the owner already closed on Hyperliquid: records it closed
// at the price entered - nothing is sent to the exchange
// (docs/api.md - POST /positions/{id}/closed-on-exchange).
export function ClosedOnExchangeButton({ position }: { position: OpenPosition }) {
  const fetcher = useFetcher<ActionResult>();
  const [open, setOpen] = useState(false);
  const label = `${position.direction} ${position.asset}`;
  const submitted = fetcher.state === "idle" && fetcher.data !== undefined;

  useEffect(() => {
    if (submitted && !fetcher.data?.error) setOpen(false);
  }, [submitted, fetcher.data]);

  return (
    <Dialog open={open} onOpenChange={setOpen}>
      <DialogTrigger
        render={<Button variant="ghost" size="icon-xs" title={`${label} doesn't exist on Hyperliquid`} />}
      >
        <Ban />
      </DialogTrigger>
      <DialogContent>
        <fetcher.Form method="post" className="space-y-4">
          <input type="hidden" name="intent" value="closedOnExchange" />
          <input type="hidden" name="positionId" value={String(position.id)} />
          <DialogHeader>
            <DialogTitle>Live {label} doesn't exist?</DialogTitle>
            <DialogDescription>
              Only if you already closed it on Hyperliquid (or it was liquidated there). Enter the price it
              closed at - the position is recorded as closed with that price. No order is sent.
            </DialogDescription>
          </DialogHeader>
          <label className="flex flex-col gap-1 text-sm">
            Close price
            <input
              name="closePrice"
              type="number"
              step="any"
              min="0"
              required
              placeholder={position.current_price ?? ""}
              className={FIELD_CLASS}
            />
          </label>
          {fetcher.data?.error && <p className="text-sm text-destructive">{fetcher.data.error}</p>}
          <DialogFooter>
            <DialogClose render={<Button type="button" variant="outline" />}>Cancel</DialogClose>
            <Button type="submit" variant="destructive" disabled={fetcher.state !== "idle"}>
              Mark closed
            </Button>
          </DialogFooter>
        </fetcher.Form>
      </DialogContent>
    </Dialog>
  );
}
