import { type ReactNode, Suspense, useEffect, useMemo, useRef, useState } from "react";
import { Await } from "react-router";

import type { Loaded } from "@/lib/api";
import { reportReachable } from "@/lib/unreachable";

// One part of the page: its skeleton while its data streams in, then the
// data - and when the API can't be reached, the last data it had (a toast
// says so). Refreshes keep the current data on screen until the new arrives:
// only the first load suspends - a refresh's pending promise would hold the
// router's transition, and with it every fetcher's state (busy buttons).
export function Section<T>({
  name,
  data,
  fallback,
  children,
}: {
  name: string; // which part failed, for the toast
  data: Promise<Loaded<T>>;
  fallback: ReactNode;
  // stale: the latest load failed - `value` is the last one that didn't.
  children: (value: T | null, stale: boolean) => ReactNode;
}) {
  const [settled, setSettled] = useState<Loaded<T> | null>(null);
  useEffect(() => {
    let current = true;
    // Rejected (e.g. cut off by the stream's timeout): a failed load.
    void data.then(
      (loaded) => {
        if (current) {
          setSettled(loaded);
        }
      },
      () => {
        if (current) {
          setSettled({ ok: false });
        }
      },
    );
    return () => {
      current = false;
    };
  }, [data]);
  return (
    <Suspense fallback={fallback}>
      <Await resolve={settled ?? data} errorElement={fallback}>
        {(loaded) => (
          <Kept name={name} loaded={loaded}>
            {children}
          </Kept>
        )}
      </Await>
    </Suspense>
  );
}

// A load whose data didn't arrive whole - "ok" without its data (seen at
// times while switching charts, the cause not caught yet): a failed one, and
// logged with the raw value to find it.
function checked<T>(name: string, loaded: Loaded<T> | undefined): Loaded<T> {
  if (loaded?.ok === false || (loaded?.ok === true && loaded.data !== undefined)) {
    return loaded;
  }
  console.warn(`section ${name}: loaded without its data`, loaded);
  return { ok: false };
}

function Kept<T>({
  name,
  loaded: raw,
  children,
}: {
  name: string;
  loaded: Loaded<T> | undefined;
  children: (value: T | null, stale: boolean) => ReactNode;
}) {
  const loaded = useMemo(() => checked(name, raw), [name, raw]);
  const last = useRef<T | null>(null);
  if (loaded.ok) {
    last.current = loaded.data;
  }
  useEffect(() => {
    if (!loaded.ok && loaded.login) {
      window.location.assign("/login");
      return;
    }
    reportReachable("api", name, loaded.ok, "API unreachable");
  }, [name, loaded]);
  return children(loaded.ok ? loaded.data : last.current, !loaded.ok);
}
