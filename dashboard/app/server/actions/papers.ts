import { api } from "@/lib/api";
import { exitsBody, managementBody } from "@/server/papers/form-bodies";
import type { PaperSweep, SweepBatch } from "@/types/sweep";

import { formId } from "./form-id";
import type { ActionHandler } from "./types";

const paperId = (form: FormData) => formId(form, "paperId");

export const paperActions: Record<string, ActionHandler> = {
  createPaper: (request, form) =>
    api(request, "/papers", {
      method: "POST",
      body: {
        kind: form.get("kind") ?? "single",
        asset: form.get("asset"),
        timeframe: form.get("timeframe"),
        direction: form.get("direction"),
        executor: form.get("executor"),
        leverage: String(form.get("leverage") ?? "1.0"),
        ...managementBody(form),
        ...exitsBody(form),
      },
    }),
  updatePaper: (request, form) =>
    api(request, `/papers/${paperId(form)}`, {
      method: "PATCH",
      body: {
        leverage: String(form.get("leverage") ?? "1.0"),
        ...managementBody(form),
        ...exitsBody(form),
      },
      // An averaging paper's backtest re-runs within the request.
      timeoutMs: 60_000,
    }),
  paperLive: (request, form) =>
    api(request, `/papers/${paperId(form)}/live`, { method: "POST" }),
  paperDisable: (request, form) =>
    api(request, `/papers/${paperId(form)}/disable`, { method: "POST" }),
  paperEnable: (request, form) =>
    api(request, `/papers/${paperId(form)}/enable`, { method: "POST" }),
  paperDelete: (request, form) => api(request, `/papers/${paperId(form)}`, { method: "DELETE" }),
  // Starts it in the API's background; the dialog polls /sweep-status.
  sweepPaper: (request, form) =>
    api<PaperSweep>(request, `/papers/${paperId(form)}/sweep`, {
      method: "POST",
      body: {
        max_leverage: String(form.get("max_leverage") ?? ""),
        // An averaging paper's only: a single paper's form has none.
        max_margin: form.get("max_margin") ? String(form.get("max_margin")) : null,
      },
      timeoutMs: 30_000,
    }),
  // Several averaging papers' sweeps one after another, each on the same budget.
  startBatch: (request, form) =>
    api<SweepBatch>(request, "/sweeps/batch", {
      method: "POST",
      body: {
        paper_ids: form.getAll("paperIds").map(Number),
        max_margin: String(form.get("max_margin") ?? ""),
      },
      timeoutMs: 30_000,
    }),
  // Its running paper's sweep too; the runs stored so far kept.
  stopBatch: (request) =>
    api<SweepBatch>(request, "/sweeps/batch/stop", { method: "POST", timeoutMs: 30_000 }),
  // Kept: the runs stored so far.
  stopSweep: (request, form) =>
    api<PaperSweep>(request, `/papers/${paperId(form)}/sweep/stop`, {
      method: "POST",
      timeoutMs: 30_000,
    }),
};
