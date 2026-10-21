import { TruncatedText } from "@/components/truncated-text";
import type { Paper } from "@/types/paper";

import { PrepStatus } from "./prep-status";

// Preparing / enabled / blocked by the risk engine / disabled (by whom and why).
export function PaperStatus({ paper }: { paper: Paper }) {
  if (paper.prep_status) return <PrepStatus paper={paper} />;
  if (paper.enabled && paper.blocked_reason) {
    return (
      <TruncatedText
        text={`blocked by risk engine — ${paper.blocked_reason}`}
        className="max-w-64 text-amber-400"
      />
    );
  }
  if (paper.enabled) return <>enabled</>;
  return (
    <TruncatedText
      text={`disabled by ${paper.disabled_by ?? ""}${paper.disabled_reason ? ` — ${paper.disabled_reason}` : ""}`}
      className="max-w-64"
    />
  );
}
