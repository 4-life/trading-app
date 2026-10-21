import { AutoOpenSwitch } from "@/components/auto-open-switch";
import { CardSkeleton } from "@/components/card-skeleton";
import { Section } from "@/components/section";
import { StatsCard } from "@/components/stats";
import type { HomeData } from "@/server/home/loader";

export function LiveSection({ live, autoOpen }: Pick<HomeData, "live" | "autoOpen">) {
  return (
    <Section name="live" data={live} fallback={<CardSkeleton title="Live" rows={2} />}>
      {(portfolio) => (
        <StatsCard
          title="Live"
          portfolio={portfolio}
          accent="border-l-amber-400"
          action={
            <Section name="auto-open" data={autoOpen} fallback={null}>
              {(a) => <AutoOpenSwitch enabled={a?.enabled ?? null} />}
            </Section>
          }
        />
      )}
    </Section>
  );
}
