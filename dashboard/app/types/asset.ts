// GET /assets (docs/market-data.md#asset-universe).
export interface Asset {
  symbol: string;
  in_use: boolean; // a paper needs it - can't be deleted
}
