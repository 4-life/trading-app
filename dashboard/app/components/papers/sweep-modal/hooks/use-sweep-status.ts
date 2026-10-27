import { useEffect, useRef, useState } from "react";

import type { Paper } from "@/types/paper";
import type { PaperSweep, SweepStatus } from "@/types/sweep";

import { SWEEP_ASCENDING, SWEEP_POLL_MS } from "../../constants";

// A paper's settings sweep, its best runs so far by `sort` (`robust`: the
// drained and tight ones left out) and the sweep
// running on the server (/sweep-status): loaded on open, on a new sort and
// whenever `started` / `stopped` (the start and stop actions' results)
// change; polled every SWEEP_POLL_MS while it - or another paper's - runs.
export function useSweepStatus(
  paper: Pick<Paper, "id" | "kind">,
  sort: string,
  robust: boolean,
  { starting, started, stopped }: { starting: boolean; started: unknown; stopped: unknown },
) {
  const [status, setStatus] = useState<SweepStatus | null>(null);
  const [loadError, setLoadError] = useState<string | null>(null);
  const [tick, setTick] = useState(0);
  const [loaded, setLoaded] = useState(0); // attempts so far - re-arms the poll
  // Started, its new status not loaded yet: from the click until the first
  // status loaded after the start's answer (no gap showing the old sweep).
  const [pending, setPending] = useState(false);
  // The start's answer when it was clicked: a new one is its answer.
  const startedAtClick = useRef(started);
  useEffect(() => {
    if (starting) {
      startedAtClick.current = started;
      setPending(true);
    }
    // Only on the click: `started` changes with the answer.
  }, [starting]);

  useEffect(() => {
    let cancelled = false;
    const answered = started !== startedAtClick.current;
    const query = new URLSearchParams({
      paper: String(paper.id),
      kind: paper.kind,
      sort,
      order: SWEEP_ASCENDING.includes(sort) ? "asc" : "desc",
      robust: robust ? "1" : "0",
    });
    fetch(`/sweep-status?${query.toString()}`)
      .then(async (response) => {
        const body = (await response.json()) as SweepStatus | { error?: string };
        if (cancelled) {
          return;
        }
        if (response.ok) {
          setStatus(body as SweepStatus);
          setLoadError(null);
        } else {
          setLoadError(("error" in body && body.error) || "couldn't load the sweep");
        }
      })
      .catch(() => {
        if (!cancelled) {
          setLoadError("API unreachable - retrying");
        }
      })
      .finally(() => {
        if (!cancelled) {
          setLoaded((n) => n + 1);
          if (answered) {
            setPending(false);
          }
        }
      });
    return () => {
      cancelled = true;
    };
  }, [paper.id, paper.kind, sort, robust, tick, started, stopped]);

  const sweep: PaperSweep | null = status?.sweep ?? null;
  const starts = starting || pending;
  const running = starts || sweep?.status === "running";
  // Another paper's sweep: this one waits for it (one at a time on the server).
  const busyPaper =
    status?.running && status.running.paper_id !== paper.id ? status.running.paper_id : null;

  // While it (or another paper's) runs: polled again SWEEP_POLL_MS after each attempt.
  useEffect(() => {
    if (!running && busyPaper === null) {
      return;
    }
    const timer = setTimeout(() => {
      setTick((n) => n + 1);
    }, SWEEP_POLL_MS);
    return () => {
      clearTimeout(timer);
    };
  }, [running, busyPaper, loaded]);

  return {
    // Starting: the previous sweep's status and runs aren't shown.
    sweep: starts ? null : sweep,
    runs: starts ? [] : (status?.runs ?? []),
    compoundRuns: starts ? [] : (status?.compound_runs ?? []),
    starting: starts,
    running,
    busyPaper,
    loadError,
    // Not known yet (just opened): no start until it is - one may be running
    // already. A failed load lets it start (a 409 then).
    checking: status === null && loadError === null,
  };
}
