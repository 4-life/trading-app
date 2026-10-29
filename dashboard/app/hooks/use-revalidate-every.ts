import { useEffect } from "react";
import { useRevalidator } from "react-router";

// Reloads the page's loader data every `ms` (fetched on the server), unless
// `paused` (e.g. a form open whose values a refresh would reset) or one is
// already under way. Not while the page is hidden - once shown again, at once.
export function useRevalidateEvery(ms: number, paused = false) {
  const revalidator = useRevalidator();
  useEffect(() => {
    const refresh = () => {
      if (revalidator.state === "idle" && !paused && !document.hidden) {
        void revalidator.revalidate();
      }
    };
    const interval = setInterval(refresh, ms);
    document.addEventListener("visibilitychange", refresh);
    return () => {
      clearInterval(interval);
      document.removeEventListener("visibilitychange", refresh);
    };
  }, [revalidator, ms, paused]);
}
