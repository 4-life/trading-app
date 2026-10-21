// API response shapes (backend/app/api). Pydantic serializes Decimal as a
// JSON string - parse with Number() before formatting.

import type { Mode } from "@/types/portfolio";

export interface Decision {
  id: number;
  decided_at: string;
  paper_id: number;
  mode: Mode;
  asset: string;
  signal: string;
  direction: string;
  reason: string;
  outcome: string;
  risk_approved: boolean | null;
  risk_reason: string | null;
  position_size_usd: string | null;
  entry_price: string | null;
  // Its filled order, if any (coins for the size).
  fill_price: string | null;
  fill_size: string | null;
  fee_usd: string | null;
  // An exit: its position's average entry; the order that closed the
  // position carries the position's whole realized PnL and margin put in.
  position_entry_price: string | null;
  closed_position: boolean;
  realized_pnl_usd: string | null;
  margin_usd: string | null;
}

export interface DecisionPage {
  items: Decision[];
  total: number;
  page: number;
  page_size: number;
}
