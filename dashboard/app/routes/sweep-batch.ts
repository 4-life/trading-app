import { api } from "@/lib/api";
import type { SweepBatch } from "@/types/sweep";

// The latest batch sweep and its progress (null: none yet), read by the batch
// dialog and polled while it runs - the API is reachable from the server only.
export async function loader({ request }: { request: Request }) {
  // The API is busy while a sweep runs: more time than the default 5 s.
  const batch = await api<SweepBatch | null>(request, "/sweeps/batch", { timeoutMs: 30_000 });
  return batch.ok
    ? Response.json({ batch: batch.data })
    : Response.json({ error: batch.error }, { status: batch.status || 502 });
}
