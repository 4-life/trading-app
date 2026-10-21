// API response shapes (backend/app/api). Pydantic serializes Decimal as a
// JSON string - parse with Number() before formatting.

export interface ExchangeApi {
  provider: string;
  keys: Record<string, string>; // masked
}

export interface Settings {
  keys: Record<string, string | null>;
  exchange_api: ExchangeApi | null; // docs/dashboard.md#exchange-api
}
