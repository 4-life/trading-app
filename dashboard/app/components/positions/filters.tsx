import type { Mode } from "@/types/portfolio";

import { FilterButton } from "./filter-button";

export type PositionState = "open" | "closed";
export type ModeFilter = Mode | "all";

// Open / closed and live / demo filters (docs/dashboard.md#positions-table).
export function PositionFilters({
  state,
  mode,
  onState,
  onMode,
}: {
  state: PositionState;
  mode: ModeFilter;
  onState: (state: PositionState) => void;
  onMode: (mode: ModeFilter) => void;
}) {
  return (
    <div className="flex flex-wrap gap-1">
      <FilterButton active={state === "open"} onClick={() => onState("open")}>
        Open
      </FilterButton>
      <FilterButton active={state === "closed"} onClick={() => onState("closed")}>
        Closed
      </FilterButton>
      <span className="mx-1 border-l border-border" />
      <FilterButton active={mode === "all"} onClick={() => onMode("all")}>
        All
      </FilterButton>
      <FilterButton active={mode === "live"} onClick={() => onMode("live")}>
        Live
      </FilterButton>
      <FilterButton active={mode === "demo"} onClick={() => onMode("demo")}>
        Demo
      </FilterButton>
    </div>
  );
}
