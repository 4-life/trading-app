import { CardSkeleton } from "@/components/card-skeleton";
import { DecisionLogCard } from "@/components/decision-log";
import { Section } from "@/components/section";
import type { HomeData } from "@/server/home/loader";

export function DecisionsSection({ decisions, assets }: Pick<HomeData, "decisions" | "assets">) {
  return (
    <Section
      name="decisions"
      data={decisions}
      fallback={<CardSkeleton title="Trading Log" rows={6} />}
    >
      {(page) => <DecisionLogCard page={page} assets={assets} />}
    </Section>
  );
}
