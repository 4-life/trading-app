export function StatCard({
  label,
  value,
  tone,
  compact = false,
}: {
  label: string;
  value: string;
  tone?: string;
  compact?: boolean; // the demo summary: smaller than the live one
}) {
  return (
    <div className={`rounded-md border border-border ${compact ? "px-1.5 py-1" : "p-3"}`}>
      <p className={`${compact ? "text-[0.65rem] leading-tight" : "text-xs"} text-muted-foreground`}>
        {label}
      </p>
      <p className={`${compact ? "text-xs leading-tight" : "text-lg"} font-semibold ${tone ?? ""}`}>
        {value}
      </p>
    </div>
  );
}
