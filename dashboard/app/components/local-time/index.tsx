import { useSyncExternalStore } from "react";

import { formatDateTime, formatTime } from "@/lib/format";

const subscribe = () => () => {};

// Times are shown in the viewer's timezone, which the server (UTC) doesn't
// know - so they're rendered after hydration only, or the server HTML and
// the browser's first render would differ (React error #418).
export function LocalTime({
  value,
  withDate = false,
}: {
  value: string | number | Date;
  withDate?: boolean;
}) {
  const hydrated = useSyncExternalStore(
    subscribe,
    () => true,
    () => false,
  );
  if (!hydrated) return null;
  return <>{withDate ? formatDateTime(value) : formatTime(value)}</>;
}
