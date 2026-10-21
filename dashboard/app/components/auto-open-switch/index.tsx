import { useFetcher } from "react-router";

import { Switch } from "@/components/ui/switch";

// Live auto-trading: while off, the app places no orders on its own for live
// papers - no entries, no exits. Off after every restart
// (docs/dashboard.md#live-cards). Shows the pending value while the change is
// in flight.
export function AutoOpenSwitch({ enabled }: { enabled: boolean | null }) {
  const fetcher = useFetcher();
  const pending = fetcher.formData?.get("enabled");
  const checked = pending != null ? pending === "true" : (enabled ?? false);
  return (
    <label className="flex items-center gap-2 text-sm font-medium">
      Auto trading
      <Switch
        checked={checked}
        disabled={enabled === null}
        onCheckedChange={(value) => {
          void fetcher.submit({ intent: "setAutoOpen", enabled: String(value) }, { method: "post" });
        }}
      />
      <span className={checked ? "text-green-500" : "text-red-500"}>{checked ? "ON" : "OFF"}</span>
    </label>
  );
}
