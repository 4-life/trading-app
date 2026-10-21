import { useFetcher } from "react-router";

import { Button } from "@/components/ui/button";
import { SETTING_LABELS } from "@/constants/settings";
import type { ActionResult } from "@/types/action";
import type { Settings } from "@/types/settings";

import { SettingField } from "./setting-field";

export function SettingsForm({ settings }: { settings: Settings }) {
  const fetcher = useFetcher<ActionResult>();
  return (
    <fetcher.Form method="post" className="space-y-3">
      <input type="hidden" name="intent" value="saveSettings" />
      {Object.entries(SETTING_LABELS).map(([key, label]) => (
        <SettingField key={key} name={key} label={label} stored={settings.keys[key] ?? null} />
      ))}
      {fetcher.data?.error && <p className="text-sm text-destructive">{fetcher.data.error}</p>}
      {fetcher.data?.saved && <p className="text-sm text-green-500">Saved</p>}
      <Button type="submit" disabled={fetcher.state !== "idle"}>
        Save
      </Button>
    </fetcher.Form>
  );
}
