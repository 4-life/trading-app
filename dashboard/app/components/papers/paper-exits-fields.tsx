import { FIELD_CLASS } from "@/lib/styles";
import type { Paper } from "@/types/paper";

// A single paper's own stop-loss and take-profit, % of the entry price,
// on top of its strategy's exits (docs/papers.md#stop-loss-and-take-profit).
// Empty: none.
export const EXIT_FIELDS = [
  ["stop_loss_pct", "Stop loss % of price"],
  ["price_take_profit_pct", "Take profit % of price"],
] as const;

export function PaperExitsFields({ paper }: { paper?: Paper }) {
  return (
    <div className="flex flex-wrap items-end gap-2">
      {EXIT_FIELDS.map(([name, label]) => {
        const value = paper?.[name];
        return (
          <label key={name} className="flex flex-col gap-0.5 text-xs text-muted-foreground">
            {label}
            <input
              name={name}
              type="number"
              step="any"
              min="0"
              placeholder="none"
              defaultValue={value === null || value === undefined ? "" : String(Number(value) * 100)}
              className={`${FIELD_CLASS} w-36`}
            />
          </label>
        );
      })}
    </div>
  );
}
