import { api } from "@/lib/api";

import { formId } from "./form-id";
import type { ActionHandler } from "./types";

const positionId = (form: FormData) => formId(form, "positionId");

export const positionActions: Record<string, ActionHandler> = {
  closePosition: (request, form) =>
    api(request, `/positions/${positionId(form)}/close`, { method: "POST" }),
  closedOnExchange: (request, form) =>
    api(request, `/positions/${positionId(form)}/closed-on-exchange`, {
      method: "POST",
      body: { close_price: String(form.get("closePrice") ?? "") },
    }),
};
