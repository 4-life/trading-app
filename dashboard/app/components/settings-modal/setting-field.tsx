import { Checkbox } from "@/components/ui/checkbox";
import { FIELD_CLASS } from "@/lib/styles";

// One integration key: new value (empty = keep the stored one), stored value
// shown masked as the placeholder, and "Remove" when something is stored.
export function SettingField({
  name,
  label,
  stored,
}: {
  name: string;
  label: string;
  stored: string | null;
}) {
  return (
    <label className="block space-y-1">
      <span className="text-sm">{label}</span>
      <div className="flex gap-2">
        <input
          name={name}
          type="password"
          autoComplete="off"
          placeholder={stored ?? "not set"}
          className={`${FIELD_CLASS} flex-1`}
        />
        {stored && (
          <label className="flex items-center gap-1 text-xs text-muted-foreground">
            <Checkbox name={`remove:${name}`} /> Remove
          </label>
        )}
      </div>
    </label>
  );
}
