// An averaging paper's fields: [name, label, a share shown in %, required].
export const MANAGEMENT_FIELDS = [
  ["initial_size_usd", "Initial size $", false, true],
  ["add_leverage", "Add leverage (max 5)", false, true],
  ["add_size_usd", "Add size $ (default: initial)", false, false],
  ["max_margin_usd", "Max margin $ (cash)", false, false],
  ["take_profit_pct", "Take profit % of margin", true, true],
  ["max_drawdown_pct", "Max drawdown % (optional)", true, false],
] as const;

// The kinds with an asset of their own: prepared and charted (a scanner
// only creates single papers).
export const ASSET_KINDS: readonly string[] = ["single", "averaging", "averaging_hedge"];
// The kinds with position management (docs/papers.md#averaging-papers).
export const AVERAGING_KINDS: readonly string[] = ["averaging", "averaging_hedge"];
