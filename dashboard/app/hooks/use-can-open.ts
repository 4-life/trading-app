import { useMemo } from "react";

import type { Loaded } from "@/lib/api";
import type { Paper } from "@/types/paper";
import type { SystemHealth } from "@/types/system-health";

// Some enabled paper could open a position right now (live ones only while
// live auto-trading is on, none with the kill switch on), for the favicon.
export function useCanOpen(
  papers: Promise<Loaded<Paper[]>>,
  autoOpen: Promise<Loaded<{ enabled: boolean }>>,
  health: Promise<Loaded<SystemHealth>>,
): Promise<Loaded<boolean>> {
  return useMemo(
    () =>
      Promise.all([papers, autoOpen, health]).then(([p, a, h]): Loaded<boolean> => {
        if (!p.ok || !a.ok || !h.ok) {
          return { ok: false };
        }
        const open = p.data.some(
          (x) => x.enabled && !x.blocked_reason && (x.mode === "demo" || a.data.enabled),
        );
        return { ok: true, data: open && !h.data.kill_switch_active };
      }),
    [papers, autoOpen, health],
  );
}
