import { useEffect, useState } from "react";
import { useFetcher } from "react-router";

import { Button } from "@/components/ui/button";
import { FIELD_CLASS } from "@/lib/styles";
import { ASSET_KINDS, AVERAGING_KINDS } from "@/constants/papers";
import type { ActionResult } from "@/types/action";

import { averagingDirections, EXECUTORS, SCANNER_EXECUTORS, TIMEFRAMES } from "../constants";
import { PaperExitsFields } from "../paper-exits-fields";
import { PositionManagementFields } from "../position-management-fields";
import { Select } from "../select";

export function CreatePaperForm({
  assets,
  onCreated,
}: {
  assets: string[];
  onCreated?: () => void;
}) {
  const fetcher = useFetcher<ActionResult>();
  // The paper went through (no error): the dialog holding the form closes.
  useEffect(() => {
    if (fetcher.state === "idle" && fetcher.data && !fetcher.data.error) {
      onCreated?.();
    }
  }, [fetcher.state, fetcher.data, onCreated]);
  const [kind, setKind] = useState("single");
  const [executor, setExecutor] = useState("vwap");
  // A scanner runs only the executors that support it, and has no asset.
  const executors = kind === "scanner" ? [...SCANNER_EXECUTORS] : Object.keys(EXECUTORS);
  return (
    <fetcher.Form method="post" className="flex flex-wrap items-end gap-2">
      <input type="hidden" name="intent" value="createPaper" />
      <Select
        name="kind"
        aria-label="Type"
        options={["single", "scanner", "averaging", "averaging_hedge"]}
        value={kind}
        onChange={(e) => {
          setKind(e.target.value);
          if (e.target.value === "scanner") setExecutor(SCANNER_EXECUTORS[0]);
        }}
      />
      <Select
        name="executor"
        options={executors}
        value={executor}
        onChange={(e) => setExecutor(e.target.value)}
      />
      {ASSET_KINDS.includes(kind) && <Select name="asset" options={assets} required />}
      <Select name="timeframe" options={TIMEFRAMES} defaultValue="15m" />
      {/* key: reset the choice when the allowed directions change */}
      <Select
        key={`${kind}-${executor}`}
        name="direction"
        options={
          AVERAGING_KINDS.includes(kind) ? averagingDirections(kind, executor) : (EXECUTORS[executor] ?? [])
        }
      />
      <input
        name="leverage"
        type="number"
        step="0.1"
        min="0.1"
        defaultValue="1.0"
        className={`${FIELD_CLASS} w-20`}
        aria-label="Leverage"
      />
      <Button type="submit" size="sm" disabled={fetcher.state !== "idle"}>
        Create paper
      </Button>
      {AVERAGING_KINDS.includes(kind) && (
        <div className="w-full pt-1">
          <PositionManagementFields />
        </div>
      )}
      {kind === "single" && (
        <div className="w-full pt-1">
          <PaperExitsFields />
        </div>
      )}
      {fetcher.data?.error && <p className="w-full text-sm text-destructive">{fetcher.data.error}</p>}
    </fetcher.Form>
  );
}
