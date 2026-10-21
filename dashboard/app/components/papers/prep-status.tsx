import { Loader2 } from "lucide-react";

import { TruncatedText } from "@/components/truncated-text";
import type { Paper } from "@/types/paper";

// A new paper's preparation (docs/papers.md#preparation): spinner while it's
// backfilled / backtested, the error if that failed, nothing once ready.
export function PrepStatus({ paper }: { paper: Paper }) {
  if (paper.prep_status === "failed") {
    return (
      <TruncatedText
        text={`preparation failed${paper.prep_error ? ` — ${paper.prep_error}` : ""}`}
        className="max-w-64 text-destructive"
      />
    );
  }
  if (!paper.prep_status) return null;
  return (
    <span className="inline-flex items-center gap-1 text-sky-400">
      <Loader2 className="size-3 animate-spin" />
      {paper.prep_status}…
    </span>
  );
}
