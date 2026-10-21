import type { Loaded } from "@/lib/api";

// Two parts' data as one (memoize it: a new promise is a new load).
export function both<A, B>(a: Promise<Loaded<A>>, b: Promise<Loaded<B>>): Promise<Loaded<[A, B]>> {
  return Promise.all([a, b]).then(([x, y]) =>
    x.ok && y.ok ? { ok: true, data: [x.data, y.data] } : { ok: false },
  );
}
