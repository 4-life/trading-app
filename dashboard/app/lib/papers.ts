import type { Paper } from "@/types/paper";

// Being backfilled / backtested - not traded or deletable yet.
export const isPreparing = (p: Pick<Paper, "prep_status">) =>
  p.prep_status === "backfilling" || p.prep_status === "backtesting";
