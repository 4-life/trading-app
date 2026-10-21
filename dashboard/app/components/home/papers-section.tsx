import { CardSkeleton } from "@/components/card-skeleton";
import { PapersCard } from "@/components/papers";
import { Section } from "@/components/section";
import type { HomeData } from "@/server/home/loader";

export function PapersSection({ papers, assets }: Pick<HomeData, "papers" | "assets">) {
  return (
    <Section name="papers" data={papers} fallback={<CardSkeleton title="Papers" rows={5} />}>
      {(p) => <PapersCard papers={p} assets={assets} />}
    </Section>
  );
}
