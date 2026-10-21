import { redirect } from "react-router";

import { ASSET_KINDS } from "@/constants/papers";
import { api, type ApiResult, type Loaded, load } from "@/lib/api";
import { getToken } from "@/lib/session";
import type { PaperChart } from "@/types/chart";
import type { DecisionPage } from "@/types/decision";
import type { Paper } from "@/types/paper";
import type { Portfolio } from "@/types/portfolio";
import type { Settings } from "@/types/settings";
import type { SystemHealth } from "@/types/system-health";

function configuredAssets(): string[] {
  try {
    const parsed: unknown = JSON.parse(process.env.ASSETS ?? "[]");
    return Array.isArray(parsed) ? parsed.map(String) : [];
  } catch {
    return [];
  }
}

// The page's data, not waited for: each part streams in as the API answers
// - the page and its skeletons render at once (components/section.tsx).
export async function loader({ request }: { request: Request }) {
  // Logged in? At once - the API's answers aren't waited for.
  if (!(await getToken(request))) {
    throw redirect("/login");
  }
  const url = new URL(request.url);
  const log = new URLSearchParams({ page: url.searchParams.get("logPage") ?? "1", page_size: "10" });
  const logMode = url.searchParams.get("logMode");
  const logAsset = url.searchParams.get("logAsset");
  if (logMode) log.set("mode", logMode);
  if (logAsset) log.set("asset", logAsset);

  const papers = load<Paper[]>(request, "/papers");
  // One chart at a time: the paper picked in ?chartPaper=, else the first
  // paper. Only that paper's chart data is fetched; null without one.
  const chart = papers.then(async (loaded): Promise<Loaded<PaperChart | null>> => {
    if (!loaded.ok) {
      return { ok: false };
    }
    const chartPapers = loaded.data.filter((p) => ASSET_KINDS.includes(p.kind));
    const picked = Number(url.searchParams.get("chartPaper"));
    const id = chartPapers.some((p) => p.id === picked) ? picked : chartPapers[0]?.id;
    // The whole stored history (15m: ~52 days) - room to scroll back through backtests.
    // A long history (an older position reached back to) takes a while.
    return id === undefined
      ? { ok: true, data: null }
      : load<PaperChart>(request, `/papers/${String(id)}/chart?limit=6000`, 20_000);
  });
  return {
    live: load<Portfolio>(request, "/portfolio?mode=live"),
    demo: load<Portfolio>(request, "/portfolio?mode=demo"),
    papers,
    decisions: load<DecisionPage>(request, `/decisions?${log.toString()}`),
    health: load<SystemHealth>(request, "/system-health"),
    autoOpen: load<{ enabled: boolean }>(request, "/auto-open"),
    // Not load(): the settings modal shows why it failed.
    settings: api<Settings>(request, "/settings").catch(
      (): ApiResult<Settings> => ({ ok: false, status: 401, error: "log in again" }),
    ),
    chart,
    assets: configuredAssets(),
  };
}

export type HomeData = Awaited<ReturnType<typeof loader>>;
