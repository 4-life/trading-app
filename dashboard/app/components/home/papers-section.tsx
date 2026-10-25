import { CardSkeleton } from "@/components/card-skeleton";
import { PapersCard } from "@/components/papers";
import { Section } from "@/components/section";
import type { HomeData } from "@/server/home/loader";

import { useWithAssets } from "./use-with-assets";

export function PapersSection({
  papers,
  assets,
}: Pick<HomeData, "papers" | "assets">) {
  const data = useWithAssets(papers, assets);
  return (
    <Section
      name="papers"
      data={data}
      fallback={<CardSkeleton title="Papers" rows={5} />}
    >
      {(d) => <PapersCard papers={d?.value ?? null} assets={d?.assets ?? []} />}
    </Section>
  );
}
