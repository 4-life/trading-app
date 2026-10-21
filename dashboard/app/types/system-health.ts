// API response shapes (backend/app/api). Pydantic serializes Decimal as a
// JSON string - parse with Number() before formatting.

export interface SystemHealth {
  checked_at: string | null;
  kill_switch_active: boolean;
  healthy: boolean;
  checks: { name: string; ok: boolean; detail: string }[];
}
