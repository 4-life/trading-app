import { FearGreedIndex } from "@/components/header/fear-greed";
import { Section } from "@/components/section";
import type { HomeData } from "@/server/home/loader";

export function FearGreedSection({ fearGreed }: Pick<HomeData, "fearGreed">) {
  return (
    <Section name="fear & greed" data={fearGreed} fallback={null}>
      {(index) => (index ? <FearGreedIndex index={index} /> : null)}
    </Section>
  );
}
