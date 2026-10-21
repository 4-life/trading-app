import type { CandleChunk } from "@/types/chart";

// The chart's older candles before `before`, with their overlays, as it
// scrolls back (/chart-candles - the API is reachable from the server only).
// Null when the dashboard answered with an error; a network failure throws.
// Called from the chart library's scroll handler, not a hook.
export async function fetchCandleChunk(
  paperId: number,
  before: string,
  limit: number,
): Promise<CandleChunk | null> {
  const query = new URLSearchParams({ paper: String(paperId), before, limit: String(limit) });
  const response = await fetch(`/chart-candles?${query.toString()}`);
  return response.ok ? ((await response.json()) as CandleChunk) : null;
}
