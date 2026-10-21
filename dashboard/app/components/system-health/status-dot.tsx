// ok null: unknown (grey).
export function StatusDot({ ok, pulse = false }: { ok: boolean | null; pulse?: boolean }) {
  const color = ok === null ? "bg-muted-foreground" : ok ? "bg-green-500" : "bg-red-500";
  return (
    <span className="relative inline-flex h-2 w-2 shrink-0" aria-hidden>
      {pulse && (
        <span className={`absolute inline-flex h-full w-full animate-ping rounded-full opacity-75 ${color}`} />
      )}
      <span className={`relative inline-block h-2 w-2 rounded-full ${color}`} />
    </span>
  );
}
