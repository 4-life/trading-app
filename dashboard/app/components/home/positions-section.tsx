import { useMemo } from "react";

import { CardSkeleton } from "@/components/card-skeleton";
import { PositionsCard } from "@/components/positions";
import { Section } from "@/components/section";
import { both } from "@/lib/loaded";
import type { HomeData } from "@/server/home/loader";

// Live and demo positions together, the latest closed first.
export function PositionsSection({ live, demo }: Pick<HomeData, "live" | "demo">) {
  const portfolios = useMemo(() => both(live, demo), [live, demo]);
  return (
    <Section
      name="positions"
      data={portfolios}
      fallback={<CardSkeleton title="Open Positions" rows={4} />}
    >
      {(p) => (
        <PositionsCard
          open={[...(p?.[0].open_positions ?? []), ...(p?.[1].open_positions ?? [])]}
          closed={[...(p?.[0].closed_positions ?? []), ...(p?.[1].closed_positions ?? [])].sort(
            (a, b) => b.closed_at.localeCompare(a.closed_at),
          )}
        />
      )}
    </Section>
  );
}
