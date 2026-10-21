import { useEffect, useState } from "react";

const format = (d: Date) => d.toISOString().slice(11, 19);

// Current UTC time, ticking every second. Rendered after hydration only -
// the server's time would never match the browser's first render.
export function UtcClock() {
  const [now, setNow] = useState<Date | null>(null);
  useEffect(() => {
    setNow(new Date());
    const id = setInterval(() => setNow(new Date()), 1000);
    return () => clearInterval(id);
  }, []);
  return (
    <span className="font-mono text-sm tabular-nums text-muted-foreground">
      {now ? `${format(now)} UTC` : null}
    </span>
  );
}
