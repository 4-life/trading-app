import {
  Dialog,
  DialogContent,
  DialogDescription,
  DialogHeader,
  DialogTitle,
} from "@/components/ui/dialog";
import type { Asset } from "@/types/asset";

import { AddAssetForm } from "./add-asset-form";
import { AssetTag } from "./asset-tag";

// The perpetuals collected live (docs/dashboard.md#assets): add any symbol,
// delete one no paper needs - with all its market data.
export function AssetsModal({
  assets,
  open,
  onOpenChange,
}: {
  assets: Asset[] | null; // null: GET /assets failed
  open: boolean;
  onOpenChange: (open: boolean) => void;
}) {
  return (
    <Dialog open={open} onOpenChange={onOpenChange}>
      <DialogContent className="sm:max-w-lg">
        <DialogHeader>
          <DialogTitle>Assets</DialogTitle>
          <DialogDescription>
            Perpetuals collected live, by the exchange's symbol. One papers use
            can't be deleted.
          </DialogDescription>
        </DialogHeader>
        {assets === null ? (
          <p className="text-sm text-destructive">Assets unavailable</p>
        ) : (
          <div className="space-y-4">
            {assets.length === 0 ? (
              <p className="text-sm text-muted-foreground">No assets yet</p>
            ) : (
              <div className="flex flex-wrap gap-2">
                {assets.map((a) => (
                  <AssetTag key={a.symbol} asset={a} />
                ))}
              </div>
            )}
            <AddAssetForm />
          </div>
        )}
      </DialogContent>
    </Dialog>
  );
}
