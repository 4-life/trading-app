import type { SystemHealth } from "@/types/system-health";

import { StatusDot } from "./status-dot";

export function CheckList({ checks }: { checks: SystemHealth["checks"] }) {
  return (
    <ul className="space-y-1">
      {checks.map((c) => (
        <li key={c.name} className="flex items-center gap-2 text-sm">
          <StatusDot ok={c.ok} />
          <span className="font-medium">{c.name}</span>
          <span className="text-muted-foreground">— {c.detail}</span>
        </li>
      ))}
    </ul>
  );
}
