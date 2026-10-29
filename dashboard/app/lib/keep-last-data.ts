import { hiddenSince } from "@/lib/page-hidden";
import { reportReachable } from "@/lib/unreachable";

// A failed refresh is tried again once after this long - a phone's network
// still waking up with the page.
const RETRY_MS = 1000;

// A route's clientLoader that keeps its last data: a refresh that can't reach
// the dashboard server keeps it (and a toast says so) instead of the error
// page. `remember` the data the page renders - the server-rendered first
// load doesn't run the clientLoader.
export function keepLastData<T>() {
  let last: T | null = null;
  return {
    async clientLoader({ serverLoader }: { serverLoader: () => Promise<T> }): Promise<T> {
      const started = Date.now();
      try {
        const data = await serverLoader().catch(async () => {
          await new Promise((resolve) => setTimeout(resolve, RETRY_MS));
          return serverLoader();
        });
        reportReachable("server", "page", true, "Dashboard server unreachable");
        return data;
      } catch (error) {
        if (last === null) {
          throw error;
        }
        // Cut off by the page going hidden: kept, no toast - the refresh on
        // showing it again reloads it.
        if (!hiddenSince(started)) {
          reportReachable("server", "page", false, "Dashboard server unreachable");
        }
        return last;
      }
    },
    remember(data: T) {
      last = data;
    },
  };
}
