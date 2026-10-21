// API decimals arrive as strings - Number() them here.
export function formatUsd(value: string | number | null | undefined): string {
  if (value === null || value === undefined) return "—";
  return Number(value).toLocaleString("en-US", { style: "currency", currency: "USD" });
}

// An asset price: 4 decimals under $1 (e.g. $0.2359), else 2.
export function formatPrice(value: string | number | null | undefined): string {
  if (value === null || value === undefined) return "—";
  const n = Number(value);
  const digits = priceDigits(n);
  return n.toLocaleString("en-US", {
    style: "currency",
    currency: "USD",
    minimumFractionDigits: digits,
    maximumFractionDigits: digits,
  });
}

export function priceDigits(price: number): number {
  return Math.abs(price) < 1 ? 4 : 2;
}

export function formatNumber(value: string | number | null | undefined, digits = 6): string {
  if (value === null || value === undefined) return "—";
  return Number(value).toLocaleString("en-US", { maximumFractionDigits: digits });
}

// Already a percentage (e.g. profitability "3.5" = 3.5%).
export function formatPercent(value: string | number): string {
  return `${Number(value).toFixed(2)}%`;
}

// PnL as a % of the margin put into the position (same basis as a paper's
// profitability), e.g. "+1.24%". Null when either value is missing.
export function pnlPercent(
  pnl: string | number | null | undefined,
  margin: string | number | null | undefined,
): string | null {
  if (pnl === null || pnl === undefined || !Number(margin)) return null;
  const pct = (Number(pnl) / Number(margin)) * 100;
  return `${pct > 0 ? "+" : ""}${formatPercent(pct)}`;
}

// 24h, no AM/PM.
export function formatTime(value: string | number | Date): string {
  return new Date(value).toLocaleTimeString("en-GB", {
    hour: "2-digit",
    minute: "2-digit",
    second: "2-digit",
    hour12: false,
  });
}

export function formatDateTime(value: string | number | Date): string {
  return new Date(value).toLocaleString("en-GB", {
    day: "2-digit",
    month: "short",
    hour: "2-digit",
    minute: "2-digit",
    hour12: false,
  });
}

export function pnlClass(value: string | number | null | undefined): string | undefined {
  const n = Number(value);
  if (!value || n === 0) return undefined;
  return n > 0 ? "text-green-500" : "text-red-500";
}
