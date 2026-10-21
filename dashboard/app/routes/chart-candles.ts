import { api } from "@/lib/api";
import type { CandleChunk } from "@/types/chart";

// The strategy chart"s older candles, fetched by the browser as it scrolls
// back (the API is reachable from the server only):
// /chart-candles?paper=<id>&before=<ISO time>&limit=<n>.
export async function loader({ request }: { request: Request }) {
  const url = new URL(request.url);
  const query = new URLSearchParams({
    before: url.searchParams.get("before") ?? "",
    limit: url.searchParams.get("limit") ?? "2000",
  });
  const paper = url.searchParams.get("paper") ?? "";
  const result = await api<CandleChunk>(
    request,
    `/papers/${encodeURIComponent(paper)}/candles?${query.toString()}`,
    { timeoutMs: 20_000 },
  );
  return result.ok
    ? Response.json(result.data)
    : Response.json({ error: result.error }, { status: result.status || 502 });
}
