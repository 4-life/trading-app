import { MANAGEMENT_FIELDS } from "@/constants/papers";

// An averaging paper's fields from a paper form: % inputs become fractions,
// empty or absent ones null (docs/papers.md#averaging-papers).
export function managementBody(form: FormData): Record<string, string | boolean | null> {
  const body: Record<string, string | boolean | null> = {};
  for (const [name, , percent] of MANAGEMENT_FIELDS) {
    const raw = String(form.get(name) ?? "").trim();
    if (raw === "") {
      body[name] = null;
    } else {
      body[name] = percent ? String(Number(raw) / 100) : raw;
    }
  }
  const start = String(form.get("backtest_start") ?? "").trim();
  body.backtest_start = start === "" ? null : `${start}T00:00:00Z`;
  body.intraday = form.get("intraday") === "on";
  body.compound_margin = form.get("compound_margin") === "on";
  body.reopen_in_trend = form.get("reopen_in_trend") === "on";
  return body;
}

// A single paper's stop-loss / take-profit from a paper form: % inputs become
// fractions, empty or absent ones null (docs/papers.md#stop-loss-and-take-profit).
export function exitsBody(form: FormData): Record<string, string | null> {
  const body: Record<string, string | null> = {};
  for (const name of ["stop_loss_pct", "price_take_profit_pct"]) {
    const raw = String(form.get(name) ?? "").trim();
    body[name] = raw === "" ? null : String(Number(raw) / 100);
  }
  return body;
}
