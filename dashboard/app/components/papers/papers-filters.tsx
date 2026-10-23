import { Switch } from "@/components/ui/switch";
import { FIELD_CLASS } from "@/lib/styles";
import type { Paper } from "@/types/paper";

import type { PaperFilter } from "./types";

// The filter without the values none of the papers has (any more): a saved
// one for a removed executor or asset would hide them all while its select,
// with no such option, shows "all".
export function knownFilter(papers: Paper[], filter: PaperFilter): PaperFilter {
  const known = (field: (typeof FIELDS)[number][0]) =>
    papers.some((p) => p[field] === filter[field]) ? filter[field] : "";
  return { ...filter, kind: known("kind"), executor: known("executor"), asset: known("asset") };
}

export function filterPapers(papers: Paper[], filter: PaperFilter, favourites: Set<number>): Paper[] {
  return papers.filter(
    (p) =>
      (!filter.kind || p.kind === filter.kind) &&
      (!filter.executor || p.executor === filter.executor) &&
      (!filter.asset || p.asset === filter.asset) &&
      (!filter.enabledOnly || p.enabled) &&
      (!filter.liveOnly || p.mode === "live") &&
      (!filter.favouritesOnly || favourites.has(p.id)),
  );
}

const FIELDS = [
  ["kind", "Type"],
  ["executor", "Executor"],
  ["asset", "Asset"],
] as const;

const TOGGLES = [
  ["enabledOnly", "Enabled only"],
  ["liveOnly", "Live only"],
  ["favouritesOnly", "Favourites only"],
] as const;

// A select per field: "all", then every value the papers have; a toggle
// for enabled papers only, one for live papers only, one for favourites only.
export function PapersFilters({
  papers,
  filter,
  onChange,
}: {
  papers: Paper[];
  filter: PaperFilter;
  onChange: (filter: PaperFilter) => void;
}) {
  return (
    <div className="flex flex-wrap items-center gap-2">
      {FIELDS.map(([field, label]) => {
        const values = [...new Set(papers.map((p) => p[field]))].sort();
        return (
          <select
            key={field}
            aria-label={label}
            className={FIELD_CLASS}
            value={filter[field]}
            onChange={(e) => onChange({ ...filter, [field]: e.target.value })}
          >
            <option value="">{`${label}: all`}</option>
            {values.map((v) => (
              <option key={v} value={v}>
                {v}
              </option>
            ))}
          </select>
        );
      })}
      {TOGGLES.map(([field, label]) => (
        <label key={field} className="flex cursor-pointer items-center gap-1.5 text-sm text-muted-foreground">
          <Switch checked={filter[field]} onCheckedChange={(on) => onChange({ ...filter, [field]: on })} />
          {label}
        </label>
      ))}
    </div>
  );
}
