import { formatUsd } from "@/lib/format";
import type { SweepRun } from "@/types/sweep";

import { SWEEP_MIN_HEADROOM } from "../constants";

const tone = (x: number) => (x >= 0 ? "text-green-500" : "text-red-500");

const RISKY_CHANCE = 0.1;

const stillOpen = (r: SweepRun) => r.positions === 0 && r.open_unrealized_usd !== 0;

// An averaging paper's sweep runs (docs/papers.md#averaging-papers). `maxMargin`:
// the sweep's, for each run's headroom - the max margin it left unused (none
// compounding: its budget is the cash). `needed`: the move a run must survive
// (the asset's adverse move x the margin; null: unknown).
export function AveragingRunsTable({
  runs,
  maxMargin,
  needed,
}: {
  runs: SweepRun[];
  maxMargin: string | null;
  needed: number | null;
}) {
  const cap = maxMargin === null ? null : Number(maxMargin);
  return (
    <div className="overflow-x-auto">
      <table className="w-full whitespace-nowrap [&_td]:pr-3 [&_th]:pr-3">
        <thead className="text-muted-foreground">
          <tr className="text-left">
            <th>Lev</th>
            <th>Initial</th>
            <th>TP</th>
            <th>Mode</th>
            <th>Total</th>
            <th>Train / test</th>
            <th>Won</th>
            <th>Give-ups</th>
            <th>Most margin</th>
            {cap !== null && <th>Headroom</th>}
            <th>Survives</th>
            <th title="The share of the strategy's entries that went past its survivable move within 7 days">
              P(give-up)
            </th>
            <th title="Expected PnL per position: its average win, less the give-up loss, at those odds">
              EV/pos
            </th>
            <th title="The probability of its cash running out">P(ruin)</th>
          </tr>
        </thead>
        <tbody>
          {runs.map((r, k) => (
            <tr key={k}>
              <td>{`×${String(r.leverage)}`}</td>
              <td>
                {r.initial_size_usd.toLocaleString("en-US", {
                  style: "currency",
                  currency: "USD",
                  maximumFractionDigits: 0,
                })}
              </td>
              <td>{`${String(Math.round(r.take_profit_pct * 1000) / 10)}%`}</td>
              <td>{r.intraday ? (r.reopen ? "intraday-reopen" : "intraday") : "hold"}</td>
              <td className={tone(r.total_usd)}>{formatUsd(String(r.total_usd))}</td>
              {stillOpen(r) ? (
                <>
                  <td className="text-muted-foreground">still open</td>
                  <td className="text-muted-foreground">still open</td>
                </>
              ) : (
                <>
                  <td>
                    <span className={tone(r.train_pnl_usd)}>
                      {formatUsd(String(r.train_pnl_usd))}
                    </span>
                    {" / "}
                    <span className={tone(r.test_pnl_usd)}>
                      {formatUsd(String(r.test_pnl_usd))}
                    </span>
                  </td>
                  <td>{`${String(r.won)}/${String(r.positions)}`}</td>
                </>
              )}
              <td>
                {`${String(r.give_ups)}${r.liquidations ? ` + ${String(r.liquidations)} liq.` : ""}`}
              </td>
              <td>{formatUsd(String(r.most_margin_usd))}</td>
              {cap !== null && <Headroom used={r.most_margin_usd} cap={cap} />}
              <Survives move={r.survivable_move_pct} needed={needed} />
              <Chance value={r.give_up_probability} />
              <td className={r.expected_pnl_usd === null ? "text-muted-foreground" : tone(r.expected_pnl_usd)}>
                {r.expected_pnl_usd === null ? "—" : formatUsd(String(r.expected_pnl_usd))}
              </td>
              <Chance value={r.ruin_probability} />
            </tr>
          ))}
        </tbody>
      </table>
    </div>
  );
}

function Headroom({ used, cap }: { used: number; cap: number }) {
  const left = cap > 0 ? 1 - used / cap : 0;
  return (
    <td className={left < SWEEP_MIN_HEADROOM ? "text-red-500" : undefined}>
      {`${String(Math.round(left * 100))}%`}
    </td>
  );
}

// How far the price can move against the first entry before the run gives up;
// red under the move it must survive.
function Survives({ move, needed }: { move: number | null; needed: number | null }) {
  if (move === null) {
    return <td className="text-muted-foreground">—</td>;
  }
  return (
    <td className={needed !== null && move < needed ? "text-red-500" : undefined}>
      {`${(move * 100).toFixed(1)}%`}
    </td>
  );
}

// A probability - red from RISKY_CHANCE.
function Chance({ value }: { value: number | null }) {
  if (value === null) {
    return <td className="text-muted-foreground">—</td>;
  }
  return (
    <td className={value >= RISKY_CHANCE ? "text-red-500" : undefined}>
      {`${(value * 100).toFixed(value < 0.01 && value > 0 ? 2 : 1)}%`}
    </td>
  );
}
