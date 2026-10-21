import { useEffect } from "react";
import { useRevalidator } from "react-router";

// Reloads the page's loader data every `ms` (fetched on the server), unless
// `paused` (e.g. a form open whose values a refresh would reset) or one is
// already under way.
export function useRevalidateEvery(ms: number, paused = false) {
  const revalidator = useRevalidator();
  useEffect(() => {
    const interval = setInterval(() => {
      if (revalidator.state === "idle" && !paused) {
        void revalidator.revalidate();
      }
    }, ms);
    return () => {
      clearInterval(interval);
    };
  }, [revalidator, ms, paused]);
}
