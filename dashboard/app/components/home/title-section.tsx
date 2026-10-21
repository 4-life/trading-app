import { useMemo } from "react";

import { Section } from "@/components/section";
import { both } from "@/lib/loaded";
import { APP_TITLE, pnlTitle } from "@/lib/page-title";
import type { HomeData } from "@/server/home/loader";

// The tab's title: the live and demo PnL.
export function TitleSection({ live, demo }: Pick<HomeData, "live" | "demo">) {
  const portfolios = useMemo(() => both(live, demo), [live, demo]);
  return (
    <Section name="portfolio" data={portfolios} fallback={<title>{APP_TITLE}</title>}>
      {(p) => <title>{p ? pnlTitle(p[0], p[1]) : APP_TITLE}</title>}
    </Section>
  );
}
