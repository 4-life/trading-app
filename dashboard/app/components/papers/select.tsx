import type { SelectHTMLAttributes } from "react";

import { FIELD_CLASS } from "@/lib/styles";

export function Select({
  name,
  options,
  ...props
}: { name: string; options: readonly string[] } & SelectHTMLAttributes<HTMLSelectElement>) {
  return (
    <select name={name} className={FIELD_CLASS} {...props}>
      {options.map((o) => (
        <option key={o} value={o}>
          {o}
        </option>
      ))}
    </select>
  );
}
