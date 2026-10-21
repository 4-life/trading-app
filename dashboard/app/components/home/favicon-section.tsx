import { Favicon } from "@/components/favicon";
import { Section } from "@/components/section";
import { useCanOpen } from "@/hooks/use-can-open";
import type { HomeData } from "@/server/home/loader";

export function FaviconSection({ papers, autoOpen, health }: Pick<HomeData, "papers" | "autoOpen" | "health">) {
  const canOpen = useCanOpen(papers, autoOpen, health);
  return (
    <Section name="favicon" data={canOpen} fallback={<Favicon active={false} />}>
      {(active) => <Favicon active={active ?? false} />}
    </Section>
  );
}
