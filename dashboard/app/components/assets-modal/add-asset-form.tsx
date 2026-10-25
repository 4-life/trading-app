import { useEffect, useRef } from "react";
import { useFetcher } from "react-router";

import { Button } from "@/components/ui/button";
import { FIELD_CLASS } from "@/lib/styles";
import type { ActionResult } from "@/types/action";

// Any symbol - not checked against the provider: the owner knows its name.
export function AddAssetForm() {
  const fetcher = useFetcher<ActionResult>();
  const form = useRef<HTMLFormElement>(null);
  const added = fetcher.state === "idle" && fetcher.data?.saved === true;

  useEffect(() => {
    if (added) {
      form.current?.reset();
    }
  }, [added]);

  return (
    <fetcher.Form ref={form} method="post" className="space-y-2">
      <input type="hidden" name="intent" value="addAsset" />
      <div className="flex gap-2">
        <input
          name="symbol"
          required
          pattern="\S+"
          maxLength={64}
          placeholder="Symbol, e.g. BTC"
          aria-label="Asset symbol"
          autoComplete="off"
          className={`${FIELD_CLASS} min-w-0 flex-1`}
        />
        <Button type="submit" disabled={fetcher.state !== "idle"}>
          Add
        </Button>
      </div>
      {fetcher.data?.error && (
        <p className="text-sm text-destructive">{fetcher.data.error}</p>
      )}
    </fetcher.Form>
  );
}
