import { useMemo } from "react";

import { Section } from "@/components/section";
import { SettingsModal } from "@/components/settings-modal";
import type { Loaded } from "@/lib/api";
import type { HomeData } from "@/server/home/loader";

// The settings modal - its GET /settings failure shown in it, so its data
// always "loads" (a Section: refreshes don't hold its forms' state).
export function SettingsSection({
  settings,
  open,
  onOpenChange,
}: Pick<HomeData, "settings"> & { open: boolean; onOpenChange: (open: boolean) => void }) {
  const result = useMemo(
    () => settings.then((r): Loaded<Awaited<HomeData["settings"]>> => ({ ok: true, data: r })),
    [settings],
  );
  return (
    <Section name="settings" data={result} fallback={null}>
      {(r) => (
        <SettingsModal
          settings={r?.ok ? r.data : null}
          error={r === null ? null : r.ok ? null : r.error}
          open={open}
          onOpenChange={onOpenChange}
        />
      )}
    </Section>
  );
}
