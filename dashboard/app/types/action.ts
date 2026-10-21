import type { PaperSweep, SweepBatch } from "@/types/sweep";

// What the home route's action returns to a form / fetcher.
export type ActionResult =
  | { error?: string; saved?: boolean; sweep?: PaperSweep; batch?: SweepBatch }
  | undefined;
