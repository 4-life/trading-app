import { SETTING_LABELS } from "@/constants/settings";
import { api } from "@/lib/api";

import type { ActionHandler } from "./types";

export const settingsActions: Record<string, ActionHandler> = {
  setAutoOpen: (request, form) =>
    api(request, "/auto-open", {
      method: "POST",
      body: { enabled: form.get("enabled") === "true" },
    }),
  reset: (request) => api(request, "/reset", { method: "POST" }),
  addExchangeApi: (request, form) => {
    const keys: Record<string, string> = {};
    for (const [name, value] of form.entries()) {
      if (name.startsWith("key:")) keys[name.slice(4)] = String(value).trim();
    }
    return api(request, "/settings/exchange-api", {
      method: "POST",
      body: { provider: form.get("provider"), keys },
      // The API checks the keys with the provider first (loads its metadata).
      timeoutMs: 30_000,
    });
  },
  deleteExchangeApi: (request) => api(request, "/settings/exchange-api", { method: "DELETE" }),
  saveSettings: (request, form) => {
    const keys: Record<string, string> = {};
    for (const key of Object.keys(SETTING_LABELS)) {
      const value = String(form.get(key) ?? "").trim();
      if (form.get(`remove:${key}`)) keys[key] = "";
      else if (value) keys[key] = value;
    }
    return api(request, "/settings", { method: "PUT", body: { keys } });
  },
};
