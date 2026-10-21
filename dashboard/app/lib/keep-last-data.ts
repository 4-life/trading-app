import { reportReachable } from "@/lib/unreachable";

// A route's clientLoader that keeps its last data: a refresh that can't reach
// the dashboard server keeps it (and a toast says so) instead of the error
// page. `remember` the data the page renders - the server-rendered first
// load doesn't run the clientLoader.
export function keepLastData<T>() {
  let last: T | null = null;
  return {
    async clientLoader({ serverLoader }: { serverLoader: () => Promise<T> }): Promise<T> {
      try {
        const data = await serverLoader();
        reportReachable("server", "page", true, "Dashboard server unreachable");
        return data;
      } catch (error) {
        if (last === null) {
          throw error;
        }
        reportReachable("server", "page", false, "Dashboard server unreachable");
        return last;
      }
    },
    remember(data: T) {
      last = data;
    },
  };
}
