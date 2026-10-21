import type { ExitSweepRun } from "@/types/sweep";

const tone = (x: number) => (x >= 0 ? "text-green-500" : "text-red-500");
const pct = (x: number) => `${x >= 0 ? "+" : ""}${x.toFixed(1)}%`;
const level = (x: number | null) => (x === null ? "—" : `${String(Math.round(x * 1000) / 10)}%`);

// A single paper's sweep runs (docs/papers.md#stop-loss-and-take-profit):
// leverage, stop-loss, take-profit and the strategy's trades compounded at
// that leverage, % of the margin.
export function ExitRunsTable({ runs }: { runs: ExitSweepRun[] }) {
  return (
    <table className="w-full">
      <thead className="text-muted-foreground">
        <tr className="text-left">
          <th>Lev</th>
          <th>SL</th>
          <th>TP</th>
          <th>Return</th>
          <th>Train / test</th>
          <th>Won</th>
          <th>SL / TP hits</th>
          <th>Liq.</th>
          <th>Max DD</th>
        </tr>
      </thead>
      <tbody>
        {runs.map((r, k) => (
          <tr key={k}>
            <td>{`×${String(r.leverage)}`}</td>
            <td>{level(r.stop_loss_pct)}</td>
            <td>{level(r.take_profit_pct)}</td>
            <td className={tone(r.return_pct)}>{pct(r.return_pct)}</td>
            <td>
              <span className={tone(r.train_return_pct)}>{pct(r.train_return_pct)}</span>
              {" / "}
              <span className={tone(r.test_return_pct)}>{pct(r.test_return_pct)}</span>
            </td>
            <td>{`${String(r.won)}/${String(r.trades)}`}</td>
            <td>{`${String(r.stops)} / ${String(r.take_profits)}`}</td>
            <td className={r.liquidations ? "text-red-500" : undefined}>{String(r.liquidations)}</td>
            <td className="text-red-500">{pct(r.max_drawdown_pct)}</td>
          </tr>
        ))}
      </tbody>
    </table>
  );
}
