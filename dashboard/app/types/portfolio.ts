// API response shapes (backend/app/api). Pydantic serializes Decimal as a
// JSON string - parse with Number() before formatting.

export type Mode = 'demo' | 'live';

export interface Stats {
  equity_usd: string;
  available_balance_usd: string;
  open_positions: number;
  exposure_usd: string;
  total_pnl_usd: string;
  unrealized_pnl_usd: string;
  realized_pnl_usd: string;
}

export interface OpenPosition {
  id: number;
  paper_id: number;
  mode: Mode;
  asset: string;
  direction: string;
  size: string;
  entry_price: string;
  current_price: string | null;
  unrealized_pnl_usd: string | null;
  exposure_usd: string | null;
  leverage: string;
  margin_usd: string;
  stop_loss_price: string | null;
  take_profit_price: string | null;
  opened_at: string;
}

export interface ClosedPosition {
  id: number;
  paper_id: number;
  mode: Mode;
  asset: string;
  direction: string;
  size: string;
  entry_price: string;
  close_price: string | null;
  margin_usd: string;
  realized_pnl_usd: string | null;
  exit_reason: string | null;
  opened_at: string;
  closed_at: string;
}

export interface Portfolio {
  mode: Mode;
  live_data: boolean;
  stats: Stats | null;
  open_positions: OpenPosition[];
  closed_positions: ClosedPosition[];
}
