import { formatDateTime } from "@/lib/format";
import type { FearGreed } from "@/types/sentiment";

// Red at extreme fear to green at extreme greed (alternative.me's bands).
function colorOf(value: number): string {
  if (value < 25) return "text-red-500";
  if (value < 45) return "text-orange-400";
  if (value <= 55) return "text-muted-foreground";
  if (value <= 75) return "text-lime-400";
  return "text-green-500";
}

// The header's crypto Fear & Greed index (docs/dashboard.md#header).
export function FearGreedIndex({ index }: { index: FearGreed }) {
  if (index.value === null) {
    return null;
  }
  const measured = index.measured_at ? `measured ${formatDateTime(index.measured_at)}` : "";
  // The source can't be read now: its last value, dimmed.
  const title = index.stale ? `last known - the source can't be read now; ${measured}` : measured;
  return (
    <span className={`text-sm text-muted-foreground ${index.stale ? "opacity-60" : ""}`} title={title}>
      Fear &amp; Greed{" "}
      <span className={`font-medium ${colorOf(index.value)}`}>
        {String(index.value)} · {index.label}
      </span>
      {index.stale && " (last known)"}
    </span>
  );
}
