import { useState } from "react";
import { useFetcher } from "react-router";

import { Select } from "@/components/papers/select";
import { Button } from "@/components/ui/button";
import { FIELD_CLASS } from "@/lib/styles";
import type { ActionResult } from "@/types/action";
import type { ExchangeApi } from "@/types/settings";

import { PROVIDER_FIELDS } from "./constants";

const PROVIDERS = Object.keys(PROVIDER_FIELDS);

// The one exchange API (docs/dashboard.md#exchange-api): shown with Delete, or
// "+ Add API" with the provider's fields. Changing it = delete, then add.
export function ExchangeApiSection({ api }: { api: ExchangeApi | null }) {
  const fetcher = useFetcher<ActionResult>();
  const [adding, setAdding] = useState(false);
  const [provider, setProvider] = useState(PROVIDERS[0]);
  const busy = fetcher.state !== "idle";
  const error = fetcher.data?.error && <p className="text-sm text-destructive">{fetcher.data.error}</p>;

  if (api) {
    return (
      <section className="space-y-2">
        <h3 className="text-sm font-medium">Exchange API</h3>
        <div className="rounded-md border p-3 text-sm">
          <p>{api.provider} · mainnet</p>
          {Object.entries(api.keys).map(([key, masked]) => (
            <p key={key} className="text-muted-foreground">
              {PROVIDER_FIELDS[api.provider]?.[key] ?? key}: {masked}
            </p>
          ))}
        </div>
        <fetcher.Form method="post">
          <input type="hidden" name="intent" value="deleteExchangeApi" />
          <Button type="submit" size="sm" variant="destructive" disabled={busy}>
            Delete API
          </Button>
        </fetcher.Form>
        {error}
      </section>
    );
  }

  return (
    <section className="space-y-2">
      <h3 className="text-sm font-medium">Exchange API</h3>
      {!adding ? (
        <>
          <p className="text-sm text-muted-foreground">
            None - demo papers use Hyperliquid mainnet market data.
          </p>
          <Button type="button" size="sm" variant="outline" onClick={() => setAdding(true)}>
            + Add API
          </Button>
        </>
      ) : (
        <fetcher.Form method="post" className="space-y-3">
          <input type="hidden" name="intent" value="addExchangeApi" />
          <Select
            name="provider"
            aria-label="Provider"
            options={PROVIDERS}
            value={provider}
            onChange={(e) => setProvider(e.target.value)}
          />
          <p className="text-xs text-muted-foreground">
            Mainnet - live papers trade real money. Test in demo mode.
          </p>
          {Object.entries(PROVIDER_FIELDS[provider] ?? {}).map(([key, label]) => (
            <label key={`${provider}:${key}`} className="block space-y-1">
              <span className="text-sm">{label}</span>
              <input
                name={`key:${key}`}
                type="password"
                autoComplete="off"
                required
                className={`${FIELD_CLASS} w-full`}
              />
            </label>
          ))}
          <div className="flex gap-2">
            <Button type="submit" size="sm" disabled={busy}>
              Save API
            </Button>
            <Button type="button" size="sm" variant="ghost" onClick={() => setAdding(false)}>
              Cancel
            </Button>
          </div>
        </fetcher.Form>
      )}
      {error}
    </section>
  );
}
