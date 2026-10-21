import { Section } from "@/components/section";
import { HealthStatus } from "@/components/system-health";
import { Skeleton } from "@/components/ui/skeleton";
import type { HomeData } from "@/server/home/loader";

export function HealthSection({ health }: Pick<HomeData, "health">) {
  return (
    <Section name="health" data={health} fallback={<Skeleton className="h-4 w-32" />}>
      {(h, stale) => <HealthStatus health={h} stale={stale} />}
    </Section>
  );
}
