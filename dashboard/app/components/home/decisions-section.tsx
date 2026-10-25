import { CardSkeleton } from "@/components/card-skeleton";
import { DecisionLogCard } from "@/components/decision-log";
import { Section } from "@/components/section";
import type { HomeData } from "@/server/home/loader";

import { useWithAssets } from "./use-with-assets";

export function DecisionsSection({
  decisions,
  assets,
}: Pick<HomeData, "decisions" | "assets">) {
  const data = useWithAssets(decisions, assets);
  return (
    <Section
      name="decisions"
      data={data}
      fallback={<CardSkeleton title="Trading Log" rows={6} />}
    >
      {(d) => (
        <DecisionLogCard page={d?.value ?? null} assets={d?.assets ?? []} />
      )}
    </Section>
  );
}
