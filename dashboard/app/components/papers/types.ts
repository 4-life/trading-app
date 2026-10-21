// What the papers table shows (papers-filters.tsx): "" = every value; the
// toggles off = enabled and disabled, demo and live.
export interface PaperFilter {
  kind: string;
  executor: string;
  asset: string;
  enabledOnly: boolean;
  liveOnly: boolean;
}
