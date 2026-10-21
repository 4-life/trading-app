import { useMemo } from "react";

import { CardSkeleton } from "@/components/card-skeleton";
import { Section } from "@/components/section";
import { StrategyChartCard } from "@/components/strategy-chart";
import { both } from "@/lib/loaded";
import type { HomeData } from "@/server/home/loader";

export function ChartSection({ papers, chart }: Pick<HomeData, "papers" | "chart">) {
  const papersChart = useMemo(() => both(papers, chart), [papers, chart]);
  return (
    <Section
      name="chart"
      data={papersChart}
      fallback={<CardSkeleton title="Chart" height="h-[560px]" />}
    >
      {(pc) => <StrategyChartCard papers={pc?.[0] ?? null} chart={pc?.[1] ?? null} />}
    </Section>
  );
}
