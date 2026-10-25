import { Trash2Icon } from "lucide-react";
import { useFetcher } from "react-router";

import { ConfirmDialog } from "@/components/confirm-dialog";
import { Button } from "@/components/ui/button";
import type { ActionResult } from "@/types/action";
import type { Asset } from "@/types/asset";

// One asset, with a trash can - off while a paper needs it.
export function AssetTag({ asset }: { asset: Asset }) {
  const fetcher = useFetcher<ActionResult>();
  const busy = fetcher.state !== "idle";
  return (
    <span className="inline-flex flex-col">
      <span className="inline-flex items-center gap-1 rounded-md border py-0.5 pr-0.5 pl-2 text-sm">
        {asset.symbol}
        <ConfirmDialog
          trigger={
            <Button
              variant="ghost"
              size="icon-xs"
              disabled={busy || asset.in_use}
              aria-label={`Delete ${asset.symbol}`}
              title={
                asset.in_use ? "Papers use it - delete them first" : undefined
              }
            />
          }
          title={`Delete ${asset.symbol}?`}
          description={`Stops collecting ${asset.symbol} and deletes all its market data: candles, trades, order books, funding, open interest and features. This can't be undone.`}
          confirmLabel="Delete"
          destructive
          onConfirm={() =>
            void fetcher.submit(
              { intent: "deleteAsset", symbol: asset.symbol },
              { method: "post" },
            )
          }
        >
          <Trash2Icon />
        </ConfirmDialog>
      </span>
      {fetcher.data?.error && (
        <span className="text-xs text-destructive">{fetcher.data.error}</span>
      )}
    </span>
  );
}
