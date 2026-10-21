import { useEffect, useState } from "react";

import type { SweepBatch } from "@/types/sweep";

import { SWEEP_POLL_MS } from "../constants";

// The latest batch sweep (/sweep-batch): loaded while `open`, again whenever
// `changed` (the start and stop actions' results) changes, and polled every
// SWEEP_POLL_MS while it runs.
export function useSweepBatch(open: boolean, changed: unknown) {
  const [batch, setBatch] = useState<SweepBatch | null>(null);
  const [loaded, setLoaded] = useState(false);
  const [loadError, setLoadError] = useState<string | null>(null);
  const [tick, setTick] = useState(0);
  const [attempts, setAttempts] = useState(0); // re-arms the poll, a failed load too

  useEffect(() => {
    if (!open) {
      return;
    }
    let cancelled = false;
    fetch("/sweep-batch")
      .then(async (response) => {
        const body = (await response.json()) as { batch?: SweepBatch | null; error?: string };
        if (cancelled) {
          return;
        }
        if (response.ok) {
          setBatch(body.batch ?? null);
          setLoadError(null);
        } else {
          setLoadError(body.error ?? "couldn't load the batch");
        }
      })
      .catch(() => {
        if (!cancelled) {
          setLoadError("API unreachable - retrying");
        }
      })
      .finally(() => {
        if (!cancelled) {
          setLoaded(true);
          setAttempts((n) => n + 1);
        }
      });
    return () => {
      cancelled = true;
    };
  }, [open, changed, tick]);

  const running = batch?.status === "running";
  useEffect(() => {
    if (!open || !running) {
      return;
    }
    const timer = setTimeout(() => {
      setTick((n) => n + 1);
    }, SWEEP_POLL_MS);
    return () => {
      clearTimeout(timer);
    };
  }, [open, running, attempts]);

  // Not known yet (just opened): no start until it is.
  return { batch, running, loadError, checking: !loaded && loadError === null };
}
