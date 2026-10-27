import { Loader2 } from "lucide-react";

import { LocalTime } from "@/components/local-time";
import type { SystemHealth } from "@/types/system-health";

import { CheckList } from "./check-list";
import { StatusDot } from "./status-dot";

// The header's watchdog status (docs/dashboard.md#system-health): all green,
// one pulsing dot; else only the failing checks and the kill switch. Stale
// (its latest load failed): the last known, a grey dot. A deploy (running, or
// its services still settling): a spinner instead of the restarts' failures -
// also while the API itself restarts (stale, the last known deploying).
export function HealthStatus({ health, stale }: { health: SystemHealth | null; stale: boolean }) {
  if (health?.deploying) {
    return (
      <span className="flex items-center gap-2 text-sm text-muted-foreground">
        <Loader2 className="size-4 animate-spin" />
        Deploying…
      </span>
    );
  }
  if (health === null || health.checked_at === null) {
    return (
      <span className="text-sm text-muted-foreground">
        {health === null ? "Health unavailable" : "No health checks yet"}
      </span>
    );
  }
  const failing = health.checks.filter((c) => !c.ok);
  if (failing.length === 0 && !health.kill_switch_active) {
    return (
      <span className="flex items-center gap-2 text-sm">
        {stale ? <StatusDot ok={null} /> : <StatusDot ok pulse />}
        {stale ? "Health: last known OK" : "All systems OK"}
        <span className="text-xs text-muted-foreground">
          · <LocalTime value={health.checked_at} />
        </span>
      </span>
    );
  }
  return (
    <div className="space-y-1">
      {stale && (
        <p className="flex items-center gap-2 text-xs text-muted-foreground">
          <StatusDot ok={null} />
          Health: last known
        </p>
      )}
      {health.kill_switch_active && (
        <p className="flex items-center gap-2 text-sm font-medium text-red-500">
          <StatusDot ok={false} />
          New positions disabled (kill switch active)
        </p>
      )}
      <CheckList checks={failing} />
    </div>
  );
}
