import { Form, useSearchParams } from "react-router";

import { Button } from "@/components/ui/button";
import { FIELD_CLASS } from "@/lib/styles";

// Live/demo and asset filters. They live in the URL (?logMode=&logAsset=),
// read by the home route's loader; submitting starts again at page 1.
export function DecisionLogFilters({ assets }: { assets: string[] }) {
  const [params] = useSearchParams();
  return (
    <Form method="get" className="flex flex-wrap gap-2" preventScrollReset>
      <select name="logMode" defaultValue={params.get("logMode") ?? ""} className={FIELD_CLASS}>
        <option value="">live + demo</option>
        <option value="live">live</option>
        <option value="demo">demo</option>
      </select>
      <select name="logAsset" defaultValue={params.get("logAsset") ?? ""} className={FIELD_CLASS}>
        <option value="">All assets</option>
        {assets.map((a) => (
          <option key={a} value={a}>
            {a}
          </option>
        ))}
      </select>
      <Button type="submit" size="sm" variant="outline">
        Filter
      </Button>
    </Form>
  );
}
