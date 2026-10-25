import { assetActions } from "@/server/actions/assets";
import { paperActions } from "@/server/actions/papers";
import { positionActions } from "@/server/actions/positions";
import { settingsActions } from "@/server/actions/settings";
import type { ActionHandler } from "@/server/actions/types";
import type { ActionResult } from "@/types/action";
import type { PaperSweep, SweepBatch } from "@/types/sweep";

const HANDLERS: Record<string, ActionHandler> = {
  ...assetActions,
  ...paperActions,
  ...positionActions,
  ...settingsActions,
};

// One action for every button on the page, dispatched by `intent`.
export async function action({ request }: { request: Request }): Promise<ActionResult> {
  const form = await request.formData();
  const intent = String(form.get("intent") ?? "");
  const handler = HANDLERS[intent] as ActionHandler | undefined;
  if (handler === undefined) {
    return { error: `unknown action ${intent}` };
  }
  const result = await handler(request, form);
  if (!result.ok) return { error: result.error };
  if (intent === "sweepPaper") return { sweep: result.data as PaperSweep };
  if (intent === "startBatch" || intent === "stopBatch") {
    return { batch: result.data as SweepBatch };
  }
  return intent === "saveSettings" || intent === "addAsset" ? { saved: true } : {};
}
