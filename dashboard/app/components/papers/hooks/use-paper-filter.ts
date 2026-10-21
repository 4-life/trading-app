import { useEffect, useState } from "react";

import { NO_FILTER, PAPER_FILTER_KEY } from "../constants";
import type { PaperFilter } from "../types";

function loadFilter(): PaperFilter {
  try {
    const saved = JSON.parse(localStorage.getItem(PAPER_FILTER_KEY) ?? "{}") as Partial<PaperFilter>;
    return {
      kind: typeof saved.kind === "string" ? saved.kind : "",
      executor: typeof saved.executor === "string" ? saved.executor : "",
      asset: typeof saved.asset === "string" ? saved.asset : "",
      enabledOnly: saved.enabledOnly === true,
      liveOnly: saved.liveOnly === true,
    };
  } catch {
    return NO_FILTER;
  }
}

function saveFilter(filter: PaperFilter) {
  try {
    localStorage.setItem(PAPER_FILTER_KEY, JSON.stringify(filter));
  } catch {
    // Not kept: all papers shown again on the next visit.
  }
}

// The papers table's filter, kept in this browser - loaded once in the
// browser (the page is rendered on the server first), saved on every change.
export function usePaperFilter(): [PaperFilter, (next: PaperFilter) => void] {
  const [filter, setFilter] = useState<PaperFilter>(NO_FILTER);
  useEffect(() => {
    setFilter(loadFilter());
  }, []);
  const change = (next: PaperFilter) => {
    saveFilter(next);
    setFilter(next);
  };
  return [filter, change];
}
