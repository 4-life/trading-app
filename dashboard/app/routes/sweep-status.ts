import { api } from "@/lib/api";
import type { ExitSweepRun, PaperSweep, SweepRun, SweepStatus } from "@/types/sweep";

// A paper's settings sweep and its best runs so far, read by the sweep dialog
// (and polled while it runs - the API is reachable from the server only):
// /sweep-status?paper=<id>&kind=<paper kind>&sort=<stat>&order=<asc|desc> -
// a single paper's runs are its exit runs. Also the sweep running on the
// server, any paper's - one at a time.
export async function loader({ request }: { request: Request }) {
  const url = new URL(request.url);
  const paper = encodeURIComponent(url.searchParams.get("paper") ?? "");
  // The API is busy while a sweep runs: more time than the default 5 s.
  const [sweep, running] = await Promise.all([
    api<PaperSweep>(request, `/papers/${paper}/sweep`, { timeoutMs: 30_000 }),
    api<PaperSweep | null>(request, "/sweeps/running", { timeoutMs: 30_000 }),
  ]);
  if (!running.ok) {
    return Response.json({ error: running.error }, { status: running.status || 502 });
  }
  if (!sweep.ok) {
    return sweep.status === 404
      ? Response.json({
          sweep: null,
          runs: [],
          compound_runs: [],
          running: running.data,
        } satisfies SweepStatus)
      : Response.json({ error: sweep.error }, { status: sweep.status || 502 });
  }
  const query = new URLSearchParams({
    sort: url.searchParams.get("sort") ?? "total_usd",
    order: url.searchParams.get("order") ?? "desc",
    limit: "5",
  });
  const single = url.searchParams.get("kind") === "single";
  const path = single ? "exit-runs" : "runs";
  // An averaging paper's runs twice: on a fixed budget and compounding.
  const compounding = new URLSearchParams(query);
  compounding.set("compound", "true");
  const [runs, compound] = await Promise.all([
    api<SweepRun[] | ExitSweepRun[]>(request, `/papers/${paper}/sweep/${path}?${query.toString()}`, {
      timeoutMs: 30_000,
    }),
    single
      ? Promise.resolve({ ok: true as const, data: [] as SweepRun[] })
      : api<SweepRun[]>(request, `/papers/${paper}/sweep/runs?${compounding.toString()}`, {
          timeoutMs: 30_000,
        }),
  ]);
  if (!runs.ok) {
    return Response.json({ error: runs.error }, { status: runs.status || 502 });
  }
  if (!compound.ok) {
    return Response.json({ error: compound.error }, { status: compound.status || 502 });
  }
  return Response.json({
    sweep: sweep.data,
    runs: runs.data,
    compound_runs: compound.data,
    running: running.data,
  } satisfies SweepStatus);
}
