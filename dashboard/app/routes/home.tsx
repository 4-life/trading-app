import { useEffect, useState } from "react";
import { type MetaFunction, useLoaderData } from "react-router";

import { Footer } from "@/components/footer";
import { Header } from "@/components/header";
import {
  ChartSection,
  DecisionsSection,
  DemoSection,
  FaviconSection,
  HealthSection,
  LiveSection,
  PapersSection,
  PositionsSection,
  SettingsSection,
  TitleSection,
} from "@/components/home";
import { useRevalidateEvery } from "@/hooks/use-revalidate-every";
import { keepLastData } from "@/lib/keep-last-data";
import type { HomeData } from "@/server/home/loader";

export { action } from "@/server/home/action";
export { loader } from "@/server/home/loader";

const REFRESH_INTERVAL_MS = 15_000;

const lastData = keepLastData<HomeData>();
export const clientLoader = lastData.clientLoader;

export const meta: MetaFunction = () => [];

export default function Home() {
  const data = useLoaderData<typeof clientLoader>();
  const [settingsOpen, setSettingsOpen] = useState(false);
  useEffect(() => {
    lastData.remember(data);
  }, [data]);
  // Loader data is fetched server-side; refreshed periodically.
  useRevalidateEvery(REFRESH_INTERVAL_MS, settingsOpen);

  return (
    <>
      <FaviconSection {...data} />
      <TitleSection {...data} />
      <div className="mx-auto max-w-[1600px] space-y-4 p-4 sm:p-6">
        <Header
          health={<HealthSection {...data} />}
          onOpenSettings={() => setSettingsOpen(true)}
        />
        <main className="space-y-4">
          <LiveSection {...data} />
          <DemoSection {...data} />
          <PositionsSection {...data} />
          <PapersSection {...data} />
          <ChartSection {...data} />
          <DecisionsSection {...data} />
        </main>
        <Footer />
      </div>
      <SettingsSection {...data} open={settingsOpen} onOpenChange={setSettingsOpen} />
    </>
  );
}
