// GET /fear-greed (docs/api.md): the crypto Fear & Greed index; nulls only if
// it was never read.
export interface FearGreed {
  value: number | null; // 0 extreme fear - 100 extreme greed
  label: string | null; // e.g. "Extreme Fear"
  measured_at: string | null;
  stale: boolean; // the last value read: its source can't be read now
}
