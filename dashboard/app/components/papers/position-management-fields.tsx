import { useEffect, useRef, useState } from "react";

import { Checkbox } from "@/components/ui/checkbox";
import { type GiveUp, giveUp } from "@/lib/averaging";
import { FIELD_CLASS } from "@/lib/styles";
import { MANAGEMENT_FIELDS } from "@/constants/papers";
import type { Paper } from "@/types/paper";

import { DateField } from "./date-field";

const asPercent = (share: number) => `${(share * 100).toFixed(1)}%`;

// A new paper's starting values, as typed (take profit in %).
const NEW_PAPER_DEFAULTS: Partial<Record<(typeof MANAGEMENT_FIELDS)[number][0], string>> = {
  initial_size_usd: "10",
  add_leverage: "5",
  max_margin_usd: "1000",
  take_profit_pct: "1",
};

// Where the automatic give-up lands with these settings, and the optional max
// drawdown's place - a short's above the first entry (+).
function describe(result: GiveUp | null, maxDrawdown: number, short: boolean): string {
  if (result === null) {
    return "Give-up: set the max margin to see where it lands (without one, adds go on until the cash runs out).";
  }
  const against = short ? "+" : "−";
  const line =
    `Gives up at ${against}${asPercent(result.drop)} from the first entry, after ${String(result.adds)} dip adds ` +
    `($${result.margin.toFixed(0)} margin) - before the liquidation at ${against}${asPercent(result.liquidation)}.`;
  if (maxDrawdown <= 0) {
    return line;
  }
  return maxDrawdown < result.drop
    ? `${line} Max drawdown ${against}${asPercent(maxDrawdown)} comes first.`
    : `${line} Max drawdown ${against}${asPercent(maxDrawdown)} is past it: never reached.`;
}

// An averaging paper's position management inputs (docs/papers.md#averaging-papers).
// Shares are typed in %. Adds come on their own, once half the margin is lost;
// the give-up is shown live from the form's values (its leverage too).
export function PositionManagementFields({ paper }: { paper?: Paper }) {
  const box = useRef<HTMLDivElement>(null);
  const [floor, setFloor] = useState<string | null>(null);

  useEffect(() => {
    const form = box.current?.closest("form");
    if (!form) {
      return;
    }
    const update = () => {
      const data = new FormData(form);
      const value = (name: string) => Number(data.get(name) ?? 0) || 0;
      const initial = value("initial_size_usd");
      // The create form's direction select, else the paper's.
      const direction = data.get("direction") ?? paper?.direction;
      const line = (short: boolean) =>
        describe(
          giveUp(
            value("leverage"),
            initial,
            value("add_size_usd") || initial,
            value("add_leverage"),
            value("max_margin_usd"),
            paper?.maintenance_margin ? Number(paper.maintenance_margin) : null,
            short,
          ),
          value("max_drawdown_pct") / 100,
          short,
        );
      // Both: a long's and a short's.
      setFloor(direction === "both" ? `Long: ${line(false)} Short: ${line(true)}` : line(direction === "short"));
    };
    update();
    form.addEventListener("input", update);
    return () => {
      form.removeEventListener("input", update);
    };
  }, []);

  return (
    <div ref={box} className="flex flex-wrap items-end gap-2">
      {MANAGEMENT_FIELDS.map(([name, label, percent, required]) => {
        const value = paper?.[name];
        const shown =
          paper === undefined
            ? (NEW_PAPER_DEFAULTS[name] ?? "")
            : value === null || value === undefined
              ? ""
              : String(Number(value) * (percent ? 100 : 1));
        return (
          <label key={name} className="flex flex-col gap-0.5 text-xs text-muted-foreground">
            {label}
            <input
              name={name}
              type="number"
              step="any"
              min="0"
              max={name === "add_leverage" ? 5 : undefined}
              required={required}
              defaultValue={shown}
              className={`${FIELD_CLASS} w-28`}
            />
          </label>
        );
      })}
      <label className="flex items-center gap-1.5 text-xs text-muted-foreground">
        <Checkbox name="intraday" defaultChecked={paper?.intraday ?? false} />
        Intraday: close at take profit at once, keep running
      </label>
      <label className="flex items-center gap-1.5 text-xs text-muted-foreground">
        <Checkbox name="reopen_in_trend" defaultChecked={paper?.reopen_in_trend ?? false} />
        Reopen in trend: intraday, a new position at the take profit candle&apos;s close while the
        strategy&apos;s trend lasts
      </label>
      <label className="flex items-center gap-1.5 text-xs text-muted-foreground">
        <Checkbox name="compound_margin" defaultChecked={paper?.compound_margin ?? false} />
        Compound: max margin grows with realized PnL
      </label>
      <DateField
        name="backtest_start"
        label="Backtest from"
        defaultValue={paper?.backtest_start?.slice(0, 10) ?? ""}
        emptyText="All history"
      />
      {floor && <p className="w-full text-xs text-muted-foreground">{floor}</p>}
    </div>
  );
}
