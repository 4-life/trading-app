import { useMemo } from "react";

import type { Loaded } from "@/lib/api";
import type { HomeData } from "@/server/home/loader";

// A section's data with the asset symbols (none if they didn't load) - for
// its asset select.
export function useWithAssets<T>(
  data: Promise<Loaded<T>>,
  assets: HomeData["assets"],
): Promise<Loaded<{ value: T; assets: string[] }>> {
  return useMemo(
    () =>
      Promise.all([data, assets]).then(([d, a]) =>
        d.ok
          ? {
              ok: true,
              data: {
                value: d.data,
                assets: a.ok ? a.data.map((x) => x.symbol) : [],
              },
            }
          : d,
      ),
    [data, assets],
  );
}
