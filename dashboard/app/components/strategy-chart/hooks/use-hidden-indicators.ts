import { useState } from "react";

import { HIDDEN_INDICATORS_KEY } from "../constants";
import type { Indicator } from "../types";

function loadHidden(): Set<Indicator> {
  try {
    return new Set(JSON.parse(localStorage.getItem(HIDDEN_INDICATORS_KEY) ?? "[]") as Indicator[]);
  } catch {
    return new Set();
  }
}

function saveHidden(hidden: Set<Indicator>) {
  try {
    localStorage.setItem(HIDDEN_INDICATORS_KEY, JSON.stringify([...hidden]));
  } catch {
    // Not kept: shown again on the next visit.
  }
}

// The chart's hidden overlays, kept in this browser (all shown by default),
// and a toggle for one of them. The chart renders in the browser only.
export function useHiddenIndicators(): [Set<Indicator>, (key: Indicator) => void] {
  const [hidden, setHidden] = useState<Set<Indicator>>(loadHidden);
  const toggle = (key: Indicator) => {
    const next = new Set(hidden);
    if (next.has(key)) {
      next.delete(key);
    } else {
      next.add(key);
    }
    saveHidden(next);
    setHidden(next);
  };
  return [hidden, toggle];
}
