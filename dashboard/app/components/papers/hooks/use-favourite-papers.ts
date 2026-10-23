import { useEffect, useState } from "react";

import { FAVOURITE_PAPERS_KEY } from "../constants";

function loadFavourites(): Set<number> {
  try {
    const saved: unknown = JSON.parse(localStorage.getItem(FAVOURITE_PAPERS_KEY) ?? "[]");
    return new Set(Array.isArray(saved) ? saved.filter((id): id is number => typeof id === "number") : []);
  } catch {
    return new Set();
  }
}

function saveFavourites(favourites: Set<number>) {
  try {
    localStorage.setItem(FAVOURITE_PAPERS_KEY, JSON.stringify([...favourites]));
  } catch {
    // Not kept: no favourites on the next visit.
  }
}

// The favourite papers' ids, kept in this browser - loaded once in the browser
// (the page is rendered on the server first), and a toggle for one of them.
export function useFavouritePapers(): [Set<number>, (id: number) => void] {
  const [favourites, setFavourites] = useState<Set<number>>(() => new Set());
  useEffect(() => {
    setFavourites(loadFavourites());
  }, []);
  const toggle = (id: number) => {
    const next = new Set(favourites);
    if (next.has(id)) {
      next.delete(id);
    } else {
      next.add(id);
    }
    saveFavourites(next);
    setFavourites(next);
  };
  return [favourites, toggle];
}
