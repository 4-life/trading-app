import { CardSkeleton } from "@/components/card-skeleton";
import { ResetButton } from "@/components/reset-button";
import { Section } from "@/components/section";
import { StatsCard } from "@/components/stats";
import type { HomeData } from "@/server/home/loader";

export function DemoSection({ demo }: Pick<HomeData, "demo">) {
  return (
    <Section name="demo" data={demo} fallback={<CardSkeleton title="Demo" rows={2} />}>
      {(portfolio) => (
        <StatsCard
          title="Demo"
          portfolio={portfolio}
          accent="border-l-sky-500"
          action={<ResetButton />}
        />
      )}
    </Section>
  );
}
