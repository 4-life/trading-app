import { api } from "@/lib/api";

import type { ActionHandler } from "./types";

// The symbol in the path encoded: a crafted one can't reach another API route.
const symbolPath = (form: FormData) =>
  encodeURIComponent(String(form.get("symbol") ?? ""));

export const assetActions: Record<string, ActionHandler> = {
  addAsset: (request, form) =>
    api(request, "/assets", {
      method: "POST",
      body: { symbol: String(form.get("symbol") ?? "").trim() },
    }),
  // All its market data goes with it - a long history takes a while.
  deleteAsset: (request, form) =>
    api(request, `/assets/${symbolPath(form)}`, {
      method: "DELETE",
      timeoutMs: 120_000,
    }),
};
