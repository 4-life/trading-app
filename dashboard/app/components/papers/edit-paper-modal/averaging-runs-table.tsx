import { formatUsd } from "@/lib/format";
import type { SweepRun } from "@/types/sweep";

const tone = (x: number) => (x >= 0 ? "text-green-500" : "text-red-500");

const stillOpen = (r: SweepRun) => r.positions === 0 && r.open_unrealized_usd !== 0;

// An averaging paper's sweep runs (docs/papers.md#averaging-papers).
export function AveragingRunsTable({ runs }: { runs: SweepRun[] }) {
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
            </tr>
          ))}
        </tbody>
      </table>
    </div>
  );
}
